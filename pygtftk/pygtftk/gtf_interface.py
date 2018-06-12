"""
Class declaration of GTF object.

When using gtfk a GTF object methods may return:

    - a GTF object (a representation of a GTF file).
    - a TAB object (a representation of a tabulated file).
    - a FASTA object (a representation of a fasta file).

"""

import gc
import os
import re
import sys
import textwrap
from collections import OrderedDict
from collections import defaultdict

from cffi import FFI
from pybedtools.bedtool import BedTool
from pyparsing import CaselessLiteral
from pyparsing import Combine
from pyparsing import Forward
from pyparsing import Literal
from pyparsing import Optional
from pyparsing import ParseResults
from pyparsing import Word
from pyparsing import nums
from pyparsing import oneOf
from pyparsing import opAssoc
from pyparsing import operatorPrecedence

import pygtftk
import pygtftk.utils
from pygtftk.fasta_interface import FASTA
from pygtftk import cmd_manager
from pygtftk.Line import Feature
from pygtftk.error import GTFtkError
from pygtftk.utils import check_file_or_dir_exists
from pygtftk.utils import chomp
from pygtftk.utils import chrom_info_to_bed_file
from pygtftk.utils import flatten_list_recur
from pygtftk.utils import make_tmp_file
from pygtftk.utils import message
from pygtftk.tab_interface import TAB

# ---------------------------------------------------------------
# find module path
# ---------------------------------------------------------------

module_path = os.path.dirname(pygtftk.__file__)

dll_path = os.path.join(module_path,
                        'lib',
                        'libgtftk.so')

# ---------------------------------------------------------------
# Load the lib
# ---------------------------------------------------------------

ffi = FFI()

gtftk_so = ffi.dlopen(dll_path)

# ---------------------------------------------------------------
# Classes for mapping C structures into Python objects
#
# ---------------------------------------------------------------

c_header = ""

ffi.cdef("""
/*
 * The structure that represents an attribute (key/value) in the last column of
 * a GTF file.
 */
typedef struct ATTRIBUTE {
    char *key, *value;
    struct ATTRIBUTE *next;
} ATTRIBUTE;

/*
 * A set of ATTRIBUTE
 */
typedef struct ATTRIBUTES {
    ATTRIBUTE **attr;
    int nb;
} ATTRIBUTES;


/*
 * A structure to store a row from a GTF file. field contains the string values
 * of the 8 first fields. Attributes are stored in the key/value string tables.
 */
typedef struct GTF_ROW {
    /*
     * the 8 first fields of a GTF file row
     */
    char **field;

    /*
     * the attributes
     */
    ATTRIBUTES attributes;

    /*
     * the rank number of the row in the GTF file
     */
    int rank;

    /*
     * the link to the next row
     */
    struct GTF_ROW *next;

} GTF_ROW;

/*
 * This is the structure that holds data in GTF format. It is also the
 * structure used as input/output for most of the functions of the library. To
 * start using the library, one must call the loadGTF() function with a GTF
 * file name in parameter and gets a pointer on a GTF_DATA in return. Then, all
 * the other functions must be called with this GTF_DATA pointer as input.
 * Their result can be another GTF_DATA pointer that can be used as input for
 * another function of the library.
 */
typedef struct GTF_DATA {
    /*
     * the number of rows
     */
    int size;

    /*
     * a table of rows
     */
    GTF_ROW **data;

    /*
     * the comments at the beginning of the file, started with "##"
     */

} GTF_DATA;

/*
 * This structure represents an index on a column, or on an attribute of the
 * last column.
 */
typedef struct INDEX {
    /*
     * the name of a column (feature, seqid, ...) or of an attribute (gene_id,
     * transcript_id, ...)
     */
    char *key;

    /*
     * the pointer on a binary tree created with tsearch C function in
     * the index_row function in column.c source file. This tree contains
     * ROW_LIST elements described later in this file and that contains a
     * token and the associated list of row numbers (the rows containing the
     * token as the value of the key (a column name or an attribute name).
     */
    void *data;

    /*
     * a reference to the GTF_DATA on which the index has been made
     */
    GTF_DATA *gtf_data;
} INDEX;

typedef struct INDEX_ID {
    int column;
    int index_rank;
} INDEX_ID;

/*
 * This is a class-like structure that modelize a column of a GTF file. It
 * contains obvious information like the name of the column, its type and the
 * indexes made on it. It contains also pointers on functions that are intended
 * to work with the corresponding values in the GTF data. There is a particular
 * function for each type of data. For example, the convert function takes a
 * string value and a default value as parameters and returns and integer
 * pointer for columns that contains integers (start, end ...), a float pointer
 * for "score" column and an ATTRIBUTES pointer for the last column. Pointers
 * on functions are initialized in the make_column function in the column.c
 * source file, depending on the type of each column.
 */
typedef struct COLUMN {
    /*
     * the rank number of the column
     */
    int num;

    /*
     * the column name : seqid, source, feature, start, end, score, strand,
     * phase or attributes
     */
    char *name;

    /*
     * the default value to print if no value is available (".")
     */
    char *default_value;

    /*
     * a table of indexes. It contains only one pointer for each column except
     * the attributes column for which there is as needed indexes (one can
     * index data on several attributes)
     */
    INDEX *index;

    /*
     * the number of indexes in the previous table
     */
    int nb_index;
} COLUMN ;

/*
 * A list of row numbers associated with a token (the values in the 8 first
 * columns or the values associated to an attribute in the last column). This
 * structure is used in the indexes as elements.
 */
typedef struct ROW_LIST {
    /*
     * the token that is contained in the rows. For example, this can be "gene"
     * or "transcript" for an index on the column feature, or "protein_coding"
     * and "lincRNA" for an index on the attribute "gene_biotype".
     */
    char *token;

    /*
     * the number of rows
     */
    int nb_row;

    /*
     * the table of row numbers
     */
    int *row;
} ROW_LIST;

/*
 * This is a structure that can hold any tabulated text. It is for example the
 * result of extract_data function. All functions that return a RAW_DATA
 * structure are "terminal" functions because this kind of result cannot be the
 * input of another function.
 */
typedef struct RAW_DATA {
    /*
     * The number of rows and columns
     */
    int nb_rows, nb_columns;

    /*
     * The name of the columns
     */
    char **column_name;

    /*
     * The data (nb_rows x nb_columns character strings)
     */
    char ***data;
} RAW_DATA;

/*
 * This structure is used to store a list of strings. Useful as a function
 * return type like get_attribute_list in get_list.c source file.
 */
typedef struct STRING_LIST {
    /*
     * the strings
     */
    char **list;

    /*
     * the size of the previous list
     */
    int nb;
} STRING_LIST;

/*
 * Used by get_sequences function to modelize exons, introns ...
 */
typedef struct SEQFRAG {
    int start, end;
    char strand;
} SEQFRAG ;

typedef struct FEATURE {
    char *name;
    int start, end, tr_start, tr_end;
} FEATURE;

typedef struct FEATURES {
    FEATURE **feature;
    int nb;
} FEATURES;

typedef struct SEQUENCE {
    char *header, *sequence, strand, *seqid, *gene_id, *transcript_id, *gene_name, *gene_biotype;
    int start, end;
    FEATURES *features;
} SEQUENCE;

typedef struct SEQUENCES {
    int nb;
    SEQUENCE **sequence;
} SEQUENCES;

typedef struct TTEXT {
    int size;
    char ***data;
} TTEXT;

/*
 * used by add_exon_number to sort exons by their start value
 */
typedef struct SORT_ROW {
    int row;
    int value;
} SORT_ROW;

/*
 * Prototypes for the visible functions (callable by external cient)
 */
GTF_DATA *load_GTF(char *input);
GTF_DATA *select_by_key(GTF_DATA *gtf_data, char *key, char *value, int not);
void print_gtf_data(GTF_DATA *gtf_data, char *output, int add_chr);
GTF_DATA *select_by_transcript_size(GTF_DATA *gtf_data, int min, int max);
GTF_DATA *select_by_number_of_exon(GTF_DATA *gtf_data, int min, int max);
GTF_DATA *select_by_genomic_location(GTF_DATA *gtf_data, int nb_loc, char **chr, int *begin_gl, int *end_gl);
RAW_DATA *extract_data(GTF_DATA *gtf_data, char *key, int base, int uniq);
void print_raw_data(RAW_DATA *raw_data, char delim, char *output);
GTF_DATA *select_transcript(GTF_DATA *gtf_data, int type);
SEQUENCES *get_sequences(GTF_DATA *gtf_data, char *genome_file, int intron, int rc);
int free_gtf_data(GTF_DATA *gtf_data);
int free_raw_data(RAW_DATA *raw_data);
char *get_memory(long int size);
int free_mem(char *ptr);
TTEXT *get_feature_list(GTF_DATA *gtf_data);
TTEXT *get_seqid_list(GTF_DATA *gtf_data);
TTEXT *get_attribute_list(GTF_DATA *gtf_data);
TTEXT *get_attribute_values_list(GTF_DATA *gtf_data, char *attribute);
GTF_DATA *convert_to_ensembl(GTF_DATA *gtf_data);
GTF_DATA *add_attributes(GTF_DATA *gtf_data, char *features, char *key, char *new_key, char *inputfile_name);
GTF_DATA *del_attributes(GTF_DATA *gtf_data, char *features, char *keys);
GTF_DATA *select_by_positions(GTF_DATA *gtf_data, int *pos, int size);
GTF_DATA *add_exon_number(GTF_DATA *gtf_data, char *exon_number_field);
GTF_DATA *add_prefix(GTF_DATA *gtf_data, char *features,  char *key, char *txt, int suffix);
GTF_DATA *merge_attr(GTF_DATA *gtf_data, char *features, char *keys, char *dest_key, char *sep);
GTF_DATA *add_attr_column(GTF_DATA *gtf_data, char *inputfile_name, char *new_key);
""")

# ---------------------------------------------------------------
# The GTF class
# ---------------------------------------------------------------

MAX_REPR_LINE = 6


class GTF(object):
    """An interface to a GTF file. This object returns a GTF, TAB
    or FASTA object.
    """

    _dll = gtftk_so
    _instance_count = 0
    _id_list = []
    _ptr_addr = []

    def __init__(
            self, input_obj=None, check_ensembl_format=True, new_data=None):
        """
        The constructor.

        :param input_obj: A File, a GTF or a string object (path).
        :param check_ensembl_format: Whether the method should search for gene/transcript feature
        to 'validate' that at least one of them can be found.
        :param new_data: Pass a pointer to a GTF_DATA to the constructor.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf) == 70
        >>> assert len(a_gtf[("feature","gene")]) == 10
        """
        cmd_manager.CmdManager.check_config_file()

        # Increment the number of instances at the
        # class level
        self._add_instance()

        # The instance number of this object is set to
        # class attribute value
        self._nb = self._instance_count

        # The list of memory IDs at the class level.
        self._id_list += [id(self)]

        if isinstance(input_obj, list):
            input_obj = input_obj[0]

        if isinstance(input_obj, file):

            if input_obj.name != '<stdin>':
                self.fn = input_obj.name
            else:
                self.fn = "-"
            self._data = 0
        elif isinstance(input_obj, str) or isinstance(input_obj, unicode):
            if isinstance(input_obj, unicode):
                input_obj = input_obj.encode("utf-8")
            if input_obj == '-':
                self.fn = "-"
            else:
                if input_obj != '<stdin>':
                    check_file_or_dir_exists(input_obj)
                    self.fn = input_obj
                    self._data = 0
                else:
                    self.fn = "-"
                    self._data = 0
        elif isinstance(input_obj, GTF):
            self.fn = input_obj.fn
            self._data = input_obj._data
        else:
            raise GTFtkError("Unsupported input type.")

        if new_data is None:

            self._data = self._dll.load_GTF(self.fn)

            if check_ensembl_format:
                tab = self.extract_data_iter_list("feature")

                not_found = True
                n = 0

                for i in tab:
                    n += 1
                    if i[0] in ["transcript", "gene"]:
                        message("Ensembl format detected.", type="DEBUG")
                        not_found = False
                        break

                if not_found:
                    msg = "Could not find any 'transcript' or 'gene' " + \
                          " line in the file. Is this GTF " + \
                          "file in ensembl format ? Try to convert it with " + \
                          "convert_ensembl command."
                    GTFtkError(msg)

            # if check_chr_gene_id:

            #    gene_to_chr = gtf.extract_data("gene_id,seqid")

        else:
            self._data = new_data

        self._message("GTF created ", type="DEBUG_MEM")
        self._ptr_addr += [id(self._data)]

    def merge_attr(self, feat="*", keys="gene_id,transcript_id",
                   new_key="gn_tx_id", sep="|"):

        if sep == "\t":
            raise GTFtkError("Tabulation is not allowed as a separator.")

        if new_key in self.get_attr_list(add_basic=False, as_dict=True):

            tmp_file = make_tmp_file(prefix="merge_attr",
                                     suffix=".txt")

            self.extract_data(keys).write(tmp_file, sep=sep)
            self = self.del_attr("*", new_key, force=True)

            self = self.add_attr_column(tmp_file, new_key)

            return self

        else:

            new_data = self._dll.merge_attr(self._data,
                                            feat,
                                            keys,
                                            new_key,
                                            sep)

            return self._clone(new_data)

    def _message(self, msg="", type='DEBUG'):
        """A processing message whose verbosity is adapted based on pygtftk.utils.VERBOSITY.

        >>> import pygtftk.utils
        >>> pygtftk.utils.VERBOSITY = 0
        >>> from pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file("simple", "gtf")[1]
        >>> gtf = GTF(a_file)
        >>> pygtftk.utils.VERBOSITY = 2
        >>> gtf._message('bla')
        >>> pygtftk.utils.VERBOSITY = 3
        >>> gtf._message('bla')
        >>> pygtftk.utils.VERBOSITY = 0
        """
        addr = re.search("([^\s]+)>", repr(self._data))
        addr = addr.group(1)
        if pygtftk.utils.VERBOSITY >= 3 :
            msg = msg + \
                  "(#lines={a}, ptr_addr={c}, file={b}, id={d}, nb={e})."
            msg = msg.format(a=self._data.size,
                             b=self.fn,
                             c=addr,
                             d=id(self),
                             e=self._nb)
            message(msg, type=type)

        elif pygtftk.utils.VERBOSITY == 2 :
            msg = msg + \
                  "(#lines={a}, ptr_addr={c}, file={b}, id={d})."
            msg = msg.format(a=self._data.size,
                             b=self.fn,
                             c=addr,
                             d=id(self))
            message(msg, type=type)

        elif pygtftk.utils.VERBOSITY == 1 :
            msg = msg + \
                  "(#lines={a}, ptr_addr={c}, file={b})."
            msg = msg.format(a=self._data.size,
                             b=self.fn,
                             c=addr)
            message(msg, type=type)

        else:
            msg = msg + \
                  "(#lines={a}, file={b})."
            msg = msg.format(a=self._data.size,
                             b=os.path.basename(self.fn))
            message(msg, type=type)

    @classmethod
    def _add_instance(cls):
        cls._instance_count += 1

    def __del__(self):
        """Delete a GTF_DATA object (set it to 0).

        :Example:

        >>> # To be used internally

        """
        if self._data != 0:
            self._message("GTF deleted ", type="DEBUG_MEM")
            self._dll.free_gtf_data(self._data)
            self._data = 0

    def head(self, nb=6, returned=False):
        """
        Print the nb first lines of the GTF object.

        :param n: The number of line to display.
        :param returned: If True, don't print but returns the message.

        """

        if not isinstance(nb, int):
            raise GTFtkError("Variable 'nb' should be an int")
        if nb < 0:
            raise GTFtkError("Variable 'nb' should be postive.")
        nb_rec = len(self)

        if self._data != 0 and nb > 0:
            msg = textwrap.dedent("""
             - A GTF object containing {a} lines:
             - File connection: {b}

             """.format(a=self._data.size,
                        b=self.fn))

            n = 1
            for i in self:
                msg += i.format() + "\n"
                if n == nb or n == nb_rec:
                    break
                n += 1
        else:
            msg = textwrap.dedent("""
             - An empty GTF object.
             - File connection: {b}
             """.format(b=self.fn))

        if returned:
            return msg
        else:
            print(msg)

    def tail(self, nb=6):
        """
        Print the nb last lines of the GTF object.

        :param n: The number of line to display.
        """

        nb_rec = len(self)

        if self._data != 0 and nb > 0:
            msg = textwrap.dedent("""
             - A GTF object containing {a} lines:
             - File connection: {b}

             """.format(a=self._data.size,
                        b=self.fn))
            if nb > nb_rec:
                nb = nb_rec

            gtf_sub = self.select_by_positions(range(nb_rec - nb, nb_rec))

            for i in gtf_sub:
                msg += i.format() + "\n"
        else:
            msg = textwrap.dedent("""
             - An empty GTF object.
             - File connection: {b}
             """.format(b=self.fn))

        print(msg)

    def __repr__(self):
        """
        Returns a printable representation of the GTF object.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf) == 70
        >>> for i in a_gtf: pass
        """

        return self.head(6, returned=True)

    def __len__(self):
        """
        Get the number of lines enclosed in the GTF object.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf) == 70
        >>> assert len(a_gtf.select_by_key("feature","gene")) == 10
        >>> assert len(a_gtf.select_by_key("feature","transcript")) == 15
        >>> assert len(a_gtf.select_by_key("feature","exon")) == 25
        >>> assert len(a_gtf.select_by_key("feature","CDS")) == 20
        """
        if self._data != 0:
            return self._data.size
        else:
            return 0

    def nrow(self):
        """
        Get the number of lines enclosed in the GTF object.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert a_gtf.nrow() == 70
        >>> assert a_gtf.select_by_key("feature","gene").nrow() == 10
        >>> assert a_gtf.select_by_key("feature","transcript").nrow() == 15
        >>> assert a_gtf.select_by_key("feature","exon").nrow() == 25
        >>> assert a_gtf.select_by_key("feature","CDS").nrow() == 20
        """
        if self._data != 0:
            return self._data.size
        else:
            return 0

    def __iter__(self):
        """
        The iterating function.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> n=0
        >>> for i in a_gtf: n += 1
        >>> assert n == 70
        >>> assert a_gtf.__iter__().next().chrom == 'chr1'
        """
        message("Interating over GTF instance.", type="DEBUG")

        for i in range(self._data.size):
            feat = Feature(ptr=self._data.data[i])
            yield feat

    def __getitem__(self, x=None):
        """Redefined indexing operator.

        :param x: A tuple (key, val), an integer or a list of integers. Indexing is zero-based.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf) == 70
        >>> assert len(a_gtf[("feature","gene")]) == 10
        >>> assert len(a_gtf[("feature","transcript")]) == 15
        >>> assert len(a_gtf[("feature","exon")]) == 25
        >>> assert len(a_gtf[("feature","CDS")]) == 20

        """

        self._message("Subsetting  GTF instance")

        if isinstance(x, tuple):
            if not len(x):
                raise GTFtkError("Need a tuple with two string or an integer")
            elif len(x) == 2:
                key, val = [str(i) for i in x]

                new_data = self._dll.select_by_key(self._data, key, val, 0)

                return self._clone(new_data)
            else:
                raise GTFtkError("Need a tuple with two string or an integer")

        elif isinstance(x, list):

            x_int = list()
            for p, i in enumerate(x):
                try:
                    # Converting to one base
                    x_int += [int(i)]
                except:
                    raise GTFtkError("Need a list of integers")

            for i in range(len(x_int)):
                if x_int[i] < 0:
                    raise GTFtkError("Need positive integers")

            new_obj = self.select_by_positions(x_int)
            return new_obj

        elif isinstance(x, int):
            if x < 0:
                raise GTFtkError("Need positive integers")
            new_obj = self.select_by_positions([x])

            return new_obj

    def _clone(self, new_data):
        """internal function to clone a GTF object."""

        a_gtf = GTF(self.fn,
                    check_ensembl_format=False,
                    new_data=new_data)

        return a_gtf

    def convert_to_ensembl(self, check_gene_chr=True):
        """Convert a GTF file to ensembl format. This method will add gene
        and transcript features if not encountered in the GTF.

        :param check_gene_chr: By default the function raise an error if several chromosomes are associated with the same gene_id.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf.select_by_key("feature", "gene,transcript", invert_match=True).convert_to_ensembl()) == len(a_gtf)

        """

        message("Calling convert_to_ensembl")
        new_data = self._dll.convert_to_ensembl(self._data)

        if check_gene_chr:
            message("Checking gene to chromosome mapping")
            tab = TAB(self.fn,
                      self._dll.extract_data(
                          self._data,
                          "gene_id,seqid",
                          1,
                          0),
                      dll=GTF._dll)

            geneid_to_chr = dict()

            for i in tab:
                gene_id, seqid = i
                if gene_id in geneid_to_chr:
                    if seqid != geneid_to_chr[gene_id]:
                        raise GTFtkError("the gene_id for {g} is "
                                         "associated to multiple chromosomes"
                                         "({c1}, {c2}). Use non ambiguous gene "
                                         "ids (e.g ensembl ids) "
                                         "please.".format(g=gene_id,
                                                          c1=seqid,
                                                          c2=geneid_to_chr[gene_id]))
                else:
                    geneid_to_chr[gene_id] = seqid

        return self._clone(new_data)

    def extract_data(self,
                     keys=None,
                     as_list=False,
                     zero_based=False,
                     no_na=False,
                     as_dict_of_values=False,
                     as_dict_of_lists=False,
                     as_dict=False,
                     as_dict_of_merged_list=False,
                     nr=False,
                     as_list_of_list=False):
        """Extract attribute values into containers of various types. Note that in case dict are requested, key are force to no_na.

        :param keys: The name of the basic or extended attributes.
        :param as_list: if true returns values for the first requested key as a list.
        :param no_na: Discard '.' (i.e undefined value).
        :param as_dict: if true returns a dict (where the key corresponds to values for the first requested key and values are set to 1). Note that '.' won't be set as a key (no need to use no_na).
        :param as_dict_of_values: if true returns a dict (where the key corresponds to values for the first requested key and the value to value encountered for the second requested key).
        :param as_dict_of_lists: if true returns a dict (where the key corresponds to values for the first requested key and the value to the last encountered list of other elements).
        :param as_dict_of_merged_list: if true returns a dict (where the key corresponds to values for the first requested key and the value to the list of other elements encountered throughout any line).
        :param as_list_of_list: if True returns a list for each line.
        :param nr: in case a as_list or as_list_of_list is choosen, return a non redondant list.
        :param zero_based: If set to True, the start position will be start-1.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_tab = a_gtf.extract_data("gene_id,transcript_id")
        >>> assert a_tab.ncols == 2
        >>> assert len(a_tab) == 70
        >>> assert len(a_gtf.extract_data("transcript_id", nr=False, as_list=True,no_na=False)) == 70
        >>> assert len(a_gtf.extract_data("transcript_id", nr=False, as_list=True,no_na=True)) == 60
        >>> assert len(a_gtf.select_by_key("feature", "transcript").extract_data("seqid,start")) == 15
        >>> assert len(a_gtf.select_by_key("feature", "transcript").extract_data("seqid,start",as_list=True))
        >>> assert a_gtf.select_by_key("feature", "transcript").extract_data("seqid,start", as_list=True, nr=True) == ['chr1']
        >>> assert a_gtf.select_by_key("feature", "transcript").extract_data("bla", as_list=True, nr=False, no_na=False).count('.') == 15
        >>> assert a_gtf.select_by_key("feature", "transcript").extract_data("bla", as_list=True, nr=True, no_na=False).count('.') == 1
        >>> assert len(a_gtf.select_by_key("feature", "transcript").extract_data("start", as_dict=True)) == 11
        >>> assert len(a_gtf.select_by_key("feature", "transcript").extract_data("seqid", as_dict=True)) == 1
        >>> assert [len(x) for x in a_gtf.select_by_key("feature", "transcript").extract_data("seqid,start", as_list_of_list=True)].count(2) == 15
        >>> assert len(a_gtf.select_by_key("feature", "transcript").extract_data("seqid,start", as_list_of_list=True, nr=True)) == 11
        """

        if keys is None:
            raise GTFtkError("Please provide a key.")

        if [as_list, as_dict, as_dict_of_lists,
            as_list_of_list,
            as_dict_of_values, as_dict_of_merged_list].count(True) > 1:
            msg = "Choose between as_list, as_dict_of_values, as_dict_of_merged_list, as_dict_of_list or as_dict"
            raise GTFtkError(msg)

        if not isinstance(keys, list):
            if isinstance(keys, str):
                keys = keys.split(",")
            else:
                raise GTFtkError("Please provide a key as str or list.")

        if zero_based:
            base = 0
        else:
            base = 1

        if nr:
            nr = 1
        else:
            nr = 0

        keys = [x if x not in ['chrom', 'chr'] else 'seqid' for x in keys]
        keys_csv = ",".join(keys)

        message("Calling extract_data (" + ",".join(keys) + ").", type="DEBUG")

        if as_list_of_list:

            ptr = self._dll.extract_data(self._data,
                                         keys_csv,
                                         base,
                                         nr)
            res_list = list()

            for i in range(ptr.nb_rows):
                sub = list()
                for j in range(ptr.nb_columns):
                    sub.append(ffi.string(ptr.data[i][j]))

                if no_na:
                    if "." not in sub:
                        res_list.append(sub)
                else:
                    res_list.append(sub)

            return res_list

        elif as_list:

            keys_csv = keys_csv.split(",")[0]

            ptr = self._dll.extract_data(self._data,
                                         keys_csv,
                                         base,
                                         nr)

            res_list = [
                ffi.string(x[0]) for x in list(
                    ptr.data[
                    0:ptr.nb_rows])]

            if no_na:
                res_list = [x for x in res_list if x != "."]

            return res_list

        elif as_dict:

            ptr = self._dll.extract_data(self._data,
                                         keys_csv,
                                         base,
                                         nr)

            res_list = [
                ffi.string(x[0]) for x in list(
                    ptr.data[
                    0:ptr.nb_rows])]

            # no_na as no effect if as_dict is requested
            res_list = [x for x in res_list if x != "."]

            return OrderedDict.fromkeys(res_list, 1)

        elif as_dict_of_lists:

            tab = TAB(self.fn,
                      self._dll.extract_data(self._data,
                                             keys_csv, base, nr),
                      dll=GTF._dll)

            if tab.ncols < 2:
                raise GTFtkError(
                    "Need at least two keys for as_dict_of_lists.")

            res_dict = OrderedDict()

            for i in tab:
                if i[0] != ".":

                    if len(i) >= 2:
                        res_dict[i[0]] = i[1:]
                    else:
                        res_dict[i[0]] = [i[1]]

            if no_na:
                for k, v in res_dict.items():
                    res_dict[k] = [x for x in v if x != "."]

            if nr:
                for k, v in res_dict.items():
                    res_dict[k] = list(OrderedDict.fromkeys(v))

            return res_dict

        elif as_dict_of_values:

            tab = TAB(self.fn,
                      self._dll.extract_data(self._data,
                                             keys_csv, base, 1),
                      dll=GTF._dll)

            if tab.ncols < 2:
                raise GTFtkError(
                    "Need at least two keys for as_dict_of_values.")

            res_dict = OrderedDict()

            for i in tab:
                if i[0] not in res_dict:
                    if i[0] != ".":
                        if no_na:
                            if i[1] != ".":
                                res_dict[i[0]] = i[1]
                        else:
                            res_dict[i[0]] = i[1]
            return res_dict

        elif as_dict_of_merged_list:

            tab = TAB(self.fn,
                      self._dll.extract_data(self._data,
                                             keys_csv, base, nr),
                      dll=GTF._dll)

            if tab.ncols < 2:
                raise GTFtkError(
                    "Need at least two keys for as_dict_of_lists.")
            res_dict = OrderedDict()

            for i in tab:

                if i[0] != ".":
                    if len(i) >= 2:
                        if i[0] in res_dict:
                            res_dict[i[0]] += i[1:]
                        else:
                            res_dict[i[0]] = i[1:]

            if no_na:
                for k, v in res_dict.items():
                    res_dict[k] = [x for x in v if x != "."]
            if nr:

                for k, v in res_dict.items():
                    res_dict[k] = list(OrderedDict.fromkeys(v))

            return res_dict
        else:
            tab = TAB(self.fn,
                      self._dll.extract_data(self._data,
                                             keys_csv,
                                             base,
                                             nr),
                      dll=GTF._dll)
            return tab

    def extract_data_iter_list(self, keys=None, zero_based=False, nr=False):
        """Extract attributes of any type and returns an iterator of lists.


        :param keys: The name of the basic or extended attributes.
        :param zero_based: If set to True, the start position will be start-1.
        :param nr: if True, return a list with non redundant items.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> gen = a_gtf.extract_data_iter_list("start,gene_id")
        >>> assert gen.next() == ['125', 'G0001']
        >>> gen =a_gtf.extract_data_iter_list("start,gene_id", zero_based=True)
        >>> assert gen.next() == ['124', 'G0001']
        >>> gen = a_gtf.extract_data_iter_list("start,gene_id")
        >>> assert len([x for x in gen]) == 70
        >>> gen = a_gtf.extract_data_iter_list("start,gene_id", nr=True)
        >>> assert len([x for x in gen]) == 26
        """

        if zero_based:
            base = 0
        else:
            base = 1

        if nr:
            nr = 1
        else:
            nr = 0

        key_list = keys.split(",")

        message("Calling extract_data_iter.", type="DEBUG")

        if not isinstance(keys, list):
            keys = keys.split(",")

        keys = [x if x not in ['chrom', 'chr'] else 'seqid' for x in keys]
        keys_csv = ",".join(keys)

        ptr = self._dll.extract_data(self._data, keys_csv, base, nr)
        nb_cols = ptr.nb_columns
        nb_rows = ptr.nb_rows

        for i in range(nb_rows):
            l = list()
            for j in range(nb_cols):
                l += [ffi.string(ptr.data[i][j])]
            yield l

    def get_gn_strand(self):
        """Returns a dict with gene IDs as keys and strands as values.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> strands = a_gtf.get_gn_strand()
        >>> assert strands['G0001'] == '+'
        >>> assert strands['G0001'] == '+'
        >>> assert strands['G0005'] == '-'
        >>> assert strands['G0006'] == '-'

        """
        strands = self.extract_data('gene_id,strand', as_dict_of_values=True, nr=True, no_na=False)
        return strands

    def get_tx_strand(self):
        """Returns a dict with transcript IDs as keys and strands as values.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> strands = a_gtf.get_tx_strand()
        >>> assert strands['G0007T001'] == '+'
        >>> assert strands['G0001T002'] == '+'
        >>> assert strands['G0009T001'] == '-'
        >>> assert strands['G0008T001'] == '-'

        """
        strands = self.extract_data('transcript_id,strand', as_dict_of_values=True, nr=True, no_na=False)
        return strands

    def get_tx_to_gn(self):
        """Returns a dict with transcripts IDs as keys and gene IDs as values."""

        my_dict = self.extract_data("transcript_id,gene_id",
                                    as_dict_of_values=True,
                                    nr=True,
                                    no_na=True)

        return my_dict

    def get_gname_to_tx(self):
        """Returns a dict with gene names as keys and the list of their associated transcripts
        as values."""

        my_dict = self.extract_data("gene_name,transcript_id",
                                    as_dict_of_merged_list=True,
                                    nr=True,
                                    no_na=True)

        return my_dict

    def get_tx_to_gname(self):
        """Returns a dict with transcript IDs as keys and gene names as values."""

        my_dict = self.extract_data("transcript_id,gene_name",
                                    as_dict_of_values=True,
                                    nr=True,
                                    no_na=True)

        return my_dict

    def add_exon_number(self, key="exon_nbr"):
        """Add exon number to exons.

        :param key: The key name to use for exon number.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_gtf = a_gtf.add_exon_number()
        >>> a_list = a_gtf.select_by_key("feature", "exon").select_by_key("transcript_id", "G0004T002").extract_data("exon_nbr", as_list=True)
        >>> assert  a_list == ['1', '2', '3']
        >>> a_list = a_gtf.select_by_key("feature", "exon").select_by_key("transcript_id", "G0003T001").extract_data("exon_nbr", as_list=True)
        >>> assert  a_list == ['2', '1']
        """

        new_data = self._dll.add_exon_number(self._data, key)
        return self._clone(new_data)

    def add_prefix(self, feat="*", key=None, txt=None, suffix=False):
        """Add a prefix to an attribute value.

        :param feat: The target features (default to all).
        :param key: The target key.
        :param txt: The string to be added as a prefix.
        :param suffix: If True append txt string as a suffix.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_gtf = a_gtf.add_prefix(feat="transcript", key="gene_id", suffix=False, txt="bla")
        >>> a_list = a_gtf.select_by_key("feature", "transcript").extract_data("gene_id", as_list=True, nr=True)
        >>> assert all([x.startswith('bla') for x in a_list])
        >>> a_gtf = a_gtf.add_prefix(feat="transcript", key="gene_id", suffix=True, txt="bla")
        >>> a_list = a_gtf.select_by_key("feature", "transcript").extract_data("gene_id", as_list=True, nr=True)
        >>> assert all([x.endswith('bla') for x in a_list])
        """

        if suffix:
            suffix = 1
        else:
            suffix = 0

        if key is None or txt is None:
            raise GTFtkError("You must provide key and txt arguments.")

        new_data = self._dll.add_prefix(self._data, feat, key, txt, suffix)
        return self._clone(new_data)

    def select_by_key(self, key=None,
                      value=None, invert_match=False,
                      file_with_values=None,
                      no_na=True,
                      col=1):
        """Select lines from a GTF based i) on attributes and values 2) on
        feature type.

        :param key: The key/attribute name to use for selection.
        :param value: Value for that key/attribute.
        :param invert_match: Boolean. Select lines that do not match that key and value.
        :param file_with_values: A file containing values (one column).
        :param col: The column number (one-based) that contains the values in the file.
        :param no_na: If invert_match is True then returns only record for which the value is defined.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b_gtf = a_gtf.select_by_key("gene_id", "G0004")
        >>> assert len(b_gtf) == 13
        >>> b_gtf = a_gtf.select_by_key("transcript_id", "G0004T002")
        >>> assert len(b_gtf) == 7
        >>> b_gtf = a_gtf.select_by_key("feature", "transcript")
        >>> assert len(b_gtf) == 15
        >>> b_gtf = a_gtf.select_by_key("feature", "gene")
        >>> assert len(b_gtf) == 10
        >>> assert len(a_gtf.select_by_key("feature", "exon")) == 25
        """

        if no_na:
            if invert_match:
                im = 2
        else:
            if invert_match:
                im = 1

        if not invert_match:
            im = 0

        if value is not None and file_with_values is not None:
            GTFtkError(
                "Please choose between 'value' and 'file_with_values' argument.")

        if invert_match and value is not None:
            value = ",".join(list(set(value.split(','))))

        key = str(key)

        if value is not None:
            value = str(value)
        else:
            if file_with_values is not None:
                value_list = []
                for line in file_with_values:
                    line = chomp(line)
                    tokens = line.split("\t")
                    if (col - 1) <= len(tokens):
                        value_list += [tokens[col - 1].strip()]
                    else:
                        GTFtkError("check column number please.")
                if len(value_list) == 0:
                    GTFtkError("No value found in input file (-f).")
                value = ",".join(list(set(value_list)))

        if key is None or value is None:
            raise GTFtkError("Need a key and value.")

        if key in ['chrom', 'chr']:
            key = 'seqid'

        if len(value) > 20:
            val_msg = value[0:19] + "..."
        else:
            val_msg = value
        msg = "Calling select_by_key (key={k}, value={v})"
        msg = msg.format(k=str(key), v=str(val_msg))

        message(msg, type="DEBUG")

        if key is None or value is None:
            # We don't know what to return.
            # The full gtf_data is returned
            new_data = self._data

        else:

            if not isinstance(key, str):
                if not isinstance(key, unicode):
                    raise GTFtkError("Key should be a string")

            if not isinstance(value, str):
                if not isinstance(value, unicode):
                    raise GTFtkError("Value should be a unicode string")

            new_data = self._dll.select_by_key(self._data,
                                               key,
                                               value,
                                               im)

            return self._clone(new_data)

    def select_by_positions(self, pos=None):
        """
        Select a set of lines by position. Numbering one-based.

        :param pos:

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert a_gtf.select_by_positions([0]).extract_data("feature", as_list=True) == ['gene']
        >>> assert a_gtf.select_by_positions(range(3)).extract_data("feature", as_list=True) == ['gene', 'transcript', 'exon']
        """

        if isinstance(pos, int):
            pos = [pos]
        elif isinstance(pos, list):
            # Check that there is only int
            if not set([type(x) for x in pos]) == {int}:
                raise GTFtkError("Only integer accepted.")
        else:
            raise GTFtkError("Only integer or list of integers accepted.")

        # get the size of the vector
        size = len(pos)

        # Prepare a table of int to avoid
        # segmentation fault for large input list.
        pos_table = ffi.new("int[]", len(pos))

        for n, val in enumerate(pos):
            pos_table[n] = val

        # Call C function
        new_data = self._dll.select_by_positions(self._data, pos_table, size)

        return self._clone(new_data)

    def select_by_regexp(self, key=None, regexp=None, invert_match=False, no_na=True):
        """Returns lines for which key value match a regular expression.

        :param key: The key/attribute name to use for selection.
        :param regexp: the regular expression
        :param invert_match: Select lines are those that do not match.
        :param no_na: Don't return records for which the value is not defined ('.').


        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b_list = a_gtf.select_by_regexp("transcript_id", "^G00[012]+T00[12]$").select_by_key("feature","transcript").extract_data("transcript_id", as_list=True)
        >>> assert b_list == ['G0001T002', 'G0001T001', 'G0002T001', 'G0010T001']

        """

        try:
            re_comp = re.compile(regexp)
        except:
            raise GTFtkError("Unsupported regular expression.")

        result = list()
        key_values = self.extract_data(key, as_list=True, no_na=False)

        for n, v in enumerate(key_values):
            if not invert_match:
                if re_comp.match(v):
                    result += [n]
                else:
                    if v == ".":
                        if not no_na:
                            result += [n]


            else:
                if not re_comp.match(v):
                    result += [n]
                else:
                    if v == ".":
                        if not no_na:
                            result += [n]
            n += 1

        return self.select_by_positions(result)

    def select_by_transcript_size(self, min=0, max=1000000000):
        """Select 'mature/spliced transcript by size.

        :param min: Minimum size for the feature.
        :param max: Maximum size for the feature.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> tx_kept = a_gtf.select_by_transcript_size(min=5, max=10)
        >>> assert len(tx_kept) == 45
        """

        message("Calling select_by_size.", type="DEBUG")

        new_data = self._dll.select_by_transcript_size(self._data, min, max)

        return self._clone(new_data)

    def select_by_loc(self, chr_str, start_str, end_str):
        """Select lines from a GTF based on genomic location.

        :param chr_str: A comma separated list of chromosomes.
        :param start_str: A comma separated list of starts.
        :param end_str: A comma separated list of ends.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b = a_gtf.select_by_loc("chr1", "125", "138")
        >>> assert len(b) == 7
        """

        if isinstance(chr_str, list):
            chr_str = ",".join(chr_str)

        if isinstance(start_str, list):
            start_str = [str(x) for x in start_str]
            start_str = ",".join(start_str)
        elif isinstance(start_str, int):
            start_str = str(start_str)

        if isinstance(end_str, list):
            end_str = [str(x) for x in end_str]
            end_str = ",".join(end_str)
        elif isinstance(end_str, int):
            end_str = str(end_str)

        chr_list = chr_str.split(",")
        start_list = start_str.split(",")
        start_list = [int(x) for x in start_list]
        end_list = end_str.split(",")
        end_list = [int(x) for x in end_list]

        nb_loc = min(len(chr_list), len(start_list), len(end_list))

        # Create pointers as input to select_by_genomic_location C function.
        chr_ptr = [ffi.new("char[]", x) for x in chr_list]
        start_ptr = start_list
        end_ptr = end_list

        msg = "Calling select_by_loc ({n} locations)."
        msg = msg.format(n=nb_loc)
        message(msg, type="DEBUG")
        # GTF_DATA *gtf_data, int nb_loc, char **chr, int *begin_gl, int
        # *end_gl
        new_data = self._dll.select_by_genomic_location(self._data,
                                                        nb_loc,
                                                        chr_ptr,
                                                        start_ptr,
                                                        end_ptr)

        return self._clone(new_data)

    def select_by_max_exon_nb(self):
        """For each gene select the transcript with the highest number of exons.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file("simple_04")[0]
        >>> a_gtf = GTF(a_file)
        >>> l = a_gtf.select_by_max_exon_nb().extract_data("transcript_id", as_list=True)
        >>> assert "G0005T001" not in l
        >>> assert "G0004T002" not in l
        >>> assert "G0006T002" not in l
        """

        nb_exons = self.nb_exons()

        info = self.extract_data("gene_id,transcript_id",
                                 as_list_of_list=True,
                                 nr=True)

        gene_to_tx_max_exon = OrderedDict()

        for i in info:
            gene_id, tx_id = i

            if gene_to_tx_max_exon.get(gene_id) is not None:
                if nb_exons[tx_id] > nb_exons[gene_to_tx_max_exon[gene_id]]:
                    gene_to_tx_max_exon[gene_id] = tx_id
            else:
                gene_to_tx_max_exon[gene_id] = tx_id

        new_data = self._dll.select_by_key(self._data,
                                           "transcript_id",
                                           ",".join(
                                               gene_to_tx_max_exon.values()),
                                           0)

        return self._clone(new_data)

    def select_by_number_of_exons(self, min=0, max=None):
        """Select transcript from a GTF based on the number of exons.

        :param min: Minimum number of exons.
        :param max: Maximum number of exons.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b = a_gtf.select_by_number_of_exons(3,3).select_by_key("feature","transcript")
        >>> assert len(b) == 3
        """

        message("Calling select_by_number_of_exons.", type="DEBUG")

        if max is None:
            max = 100000000

        new_data = self._dll.select_by_number_of_exon(self._data,
                                                      min,
                                                      max)

        return self._clone(new_data)

    def select_by_numeric_value(self,
                                bool_exp=None,
                                na_omit=None):
        """Test a numeric value. Select lines using a boolean operation on attributes.
        The boolean expression must contain attributes enclosed with braces.
        Example: "cDNA_length > 200 and tx_genomic_length > 2000".
        Note that one can refers to the name of the first columns of the gtf using e.g:
        start, end, score or frame.

        :param bool_exp: A simple boolean operation. And/or operation are not supported at the moment.
        :param na_omit: Any line for which one of the tested value is in this list wont be evaluated (e.g. ["."]).


        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b_gtf = a_gtf.add_attr_from_list(feat="transcript", key="transcript_id", key_value=["G0001T001","G0002T001","G0003T001","G0004T001"], new_key="test", new_key_value=["10","11","20","40"])
        >>> c_list = b_gtf.select_by_key("feature","transcript").select_by_numeric_value("test > 2", na_omit=".").extract_data("test", as_list=True)
        >>> assert c_list == ['10', '11', '20', '40']
        >>> a_file = get_example_file(datasetname="mini_real", ext="gtf.gz")[0]
        >>> a_gtf = GTF(a_file)
        >>> tx = a_gtf.select_by_key('feature','transcript')
        >>> assert len(tx.select_by_key("score", "0")) == len(tx.select_by_numeric_value("score == 0"))
        >>> assert len(tx.select_by_key("start", "1001145")) == len(tx.select_by_numeric_value("start == 1001145"))
        >>> assert len(tx.select_by_key("start", "1001145", invert_match=True)) == len(tx.select_by_numeric_value("start != 1001145"))
        >>> assert len(tx.select_by_key("end", "54801291")) == len(tx.select_by_numeric_value("end == 54801291"))
        >>> assert len(tx.select_by_numeric_value("end == 54801291 and start == 53802771")) == 3
        >>> assert len(tx.select_by_numeric_value("end == 54801291 and (start == 53802771 or start == 53806156)")) == 4
        >>> assert len(a_gtf.select_by_numeric_value("phase > 0 and phase < 2", na_omit=".").extract_data('phase', as_list=True,  nr=True)) == 1
        """

        if na_omit is not None:
            if not isinstance(na_omit, list):
                na_omit = na_omit.split(",")

        def _find_keys(pr, the_key='key', res=[], visited=0):
            """Should be called like that: _find_keys(pr, res=[])."""
            if isinstance(pr, ParseResults):
                if visited == 0:
                    if pr.haskeys():
                        res += pr.asDict()[the_key]
                    _find_keys(pr, the_key=the_key, res=res, visited=1)
                else:
                    for i in pr:
                        if isinstance(pr, ParseResults):
                            _find_keys(i, the_key=the_key, res=res)
            return list(set(res))

        def _embed(s, l, t):
            return 'float(i.' + t[0] + ')'

        attr_list = self.get_attr_list(add_basic=True)

        if len(attr_list) == 0:
            # The GTF does not seem to contain anything
            return self.select_by_positions([x + 1 for x in range(len(self))])

        lparen = Literal("(")
        rparen = Literal(")")
        and_operator = CaselessLiteral("and")
        or_operator = CaselessLiteral("or")
        comparison_operator = oneOf(['==', '!=', '>', '>=', '<', '<='])
        point = Literal('.')
        exponent = CaselessLiteral('E')
        plusorminus = Literal('+') | Literal('-')
        number = Word(nums)
        integer = Combine(Optional(plusorminus) + number)
        float_nb = Combine(integer +
                           Optional(point + Optional(number)) +
                           Optional(exponent + integer))
        value = float_nb
        value.resultsName = 'value'
        identifier = oneOf(attr_list,
                           caseless=False).setParseAction(_embed)
        identifier = identifier.setResultsName('key',
                                               listAllMatches=False
                                               ).setResultsName('key',
                                                                listAllMatches=True)
        group_1 = identifier + comparison_operator + value
        group_2 = value + comparison_operator + identifier
        comparison = group_1 | group_2
        boolean_expr = operatorPrecedence(comparison,
                                          [(and_operator, 2, opAssoc.LEFT),
                                           (or_operator, 2, opAssoc.LEFT)])

        boolean_expr_par = lparen + boolean_expr + rparen

        expression = Forward()
        expression << boolean_expr | boolean_expr_par

        try:
            parsed_exp = expression.parseString(bool_exp, parseAll=True)
        except:
            raise GTFtkError("Expression not supported.")

        # delete the suffix/prefixed: 'float(i.' + .* + ')'
        attr_used = [x[8:-1] for x in _find_keys(parsed_exp, res=[])]

        for i in attr_used:
            if i not in [x for x in attr_list]:
                GTFtkError("Your expression seems to contain an unknow key.")

        tab = self.extract_data(",".join(attr_used))

        parsed_exp_str = flatten_list_recur(parsed_exp.asList())

        result = []
        pos = 0

        if na_omit is None:
            for i in tab:

                try:
                    [float(x) for x in i]
                    if eval(parsed_exp_str):
                        result += [pos]
                except:
                    msg = "Found non numeric values in: '%s'." % ",".join(i)
                    GTFtkError(msg)
                pos += 1
        else:
            for i in tab:
                if not any([True if x in na_omit else False for x in i]):
                    try:
                        [float(x) for x in i]
                        if eval(parsed_exp_str):
                            result += [pos]
                    except:
                        msg = "Found non numeric values in: '%s'." % ",".join(
                            i)
                        GTFtkError(msg)
                pos += 1
        # Call C function
        return self.select_by_positions(result)

    def nb_exons(self):
        """Return a dict with transcript as key and number of exon as value.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert a_gtf.nb_exons().keys()[0] == 'G0003T001'
        >>> assert a_gtf.nb_exons().keys()[-1] == 'G0010T001'
        >>> assert a_gtf.nb_exons().values()[0] == 2
        >>> assert a_gtf.nb_exons().values()[-1] == 1
        """

        message("Calling nb_exons.", type="DEBUG")

        nb_exons = dict()
        nb_exons = defaultdict(lambda: 0, nb_exons)

        tab = self.extract_data("transcript_id,feature")
        for i in tab:
            if i[1] == 'exon':
                nb_exons[i[0]] += 1

        return nb_exons

    def get_attr_list(self, add_basic=False, as_dict=False):
        """Get the list of possible attributes from a GTF file..

        :param add_basic: add basic attributes to the list. Won't work if as_dict is True.
        :param as_dict: If True, returns a dict with the attribute names as key and number of occurence as values.

        :Example:

            >>> from  pygtftk.utils import get_example_file
            >>> from pygtftk.gtf_interface import GTF
            >>> from pygtftk.utils import TAB
            >>> a_file = get_example_file()[0]
            >>> assert "".join([x[0] for x in GTF(a_file).get_attr_list()]) == 'gtec'
        """

        message("Calling get_attr_list.", type="DEBUG")

        basic = ['seqid',
                 'source',
                 'feature',
                 'start',
                 'end',
                 'score',
                 'strand',
                 'phase']

        alist = list()

        ptr = self._dll.get_attribute_list(self._data)

        for i in range(ptr.size):
            alist += [ffi.string(ptr.data[i][0])]

        if as_dict:
            d = dict()
            for i in alist:
                d[i] = 1
            return d
        else:
            if add_basic:
                return basic + alist
            else:
                return alist

    def get_attr_value_list(self, key=None, count=False):
        """Get the list of possible values taken by an attributes from a GTF file..

        :param key: The key/attribute name to use.
        :param count: whether the number of occurences should be also returned (returns a list of list).


        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf.get_attr_value_list(key="transcript_id")) == 15
        >>> assert a_gtf.get_attr_value_list(key="transcript_id", count=True)[0] == ['G0001T001', '3']
        >>> assert a_gtf.get_attr_value_list(key="transcript_id", count=True)[-1] == ['G0010T001', '3']
        """

        message("Calling get_attr_value_list.", type="DEBUG")

        ptr = self._dll.get_attribute_values_list(self._data, key)

        alist = list()
        for i in range(ptr.size):
            if not count:
                alist += [ffi.string(ptr.data[i][1])]
            else:
                alist += [[ffi.string(ptr.data[i][1]),
                           ffi.string(ptr.data[i][0])]]

        return alist

    def add_attr_from_file(self,
                           feat=None,
                           key="transcript_id",
                           new_key="new_key",
                           inputfile=None,
                           has_header=False):
        """Add key/value pairs to the GTF object.

        :param feat: The comma separated list of target feature. If None, all the features.
        :param key: The name of the key used for joining (i.e the key corresponding to value provided in the file).
        :param new_key: A name for the novel key.
        :param inputfile: A two column (e.g transcript_id and new value) file.
        :param has_header: Whether the file to join contains column names.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> join_file = get_example_file("simple", "join")[0]
        >>> b_gtf = a_gtf.add_attr_from_file(feat="gene", key="gene_id", new_key="bla", inputfile=join_file)
        >>> b_list = b_gtf.select_by_key("feature", "gene").extract_data("bla", as_list=True, no_na=True)
        >>> assert b_list == ['0.2322', '0.999', '0.5555']

        """

        message("Calling add_attr_from_file", type="DEBUG")

        if feat is None:
            feat = "*"

        if inputfile is None:
            raise GTFtkError("Need an input/join file.")

        if isinstance(inputfile, str):
            inputfile = open(inputfile)

        message("Reading file to join.", type="DEBUG")

        tmp_file = make_tmp_file(prefix="gtftk_join_attr",
                                 suffix=".txt")

        key_to_value = defaultdict(list)

        if os.stat(inputfile.name).st_size == 0:
            raise GTFtkError("File {f} is empty.".format(f=inputfile.name))

        for line_nb, line in enumerate(inputfile):

            if has_header:
                if line_nb == 0:
                    pass
            else:
                line = chomp(line)
                fields = line.split("\t")

                try:
                    key_to_value[fields[0]] += [fields[1]]
                except:
                    GTFtkError("Does the file to join contains 2 fields ?")

        message("Found " + str(line_nb) + " lines.")
        message("Found " + str(len(key_to_value)) + " different entries.")

        if line_nb == 0:
            raise GTFtkError("File is empty.")

        for k, v in key_to_value.items():
            tmp_file.write(k + "\t" + "|".join(key_to_value[k]) + "\n")

        tmp_file.close()

        message("Calling internal C function (add_attributes)")

        new_data = self._dll.add_attributes(self._data,
                                            feat,
                                            key,
                                            new_key,
                                            tmp_file.name)

        return self._clone(new_data)

    def add_attr_from_matrix_file(self,
                                  feat=None,
                                  key="transcript_id",
                                  inputfile=None):
        """Add key/value pairs to the GTF file. Expect a matrix with row names as target keys column names as novel key and each cell as value.

        :param feat: The comma separated list of target feature. If None, all the features.
        :param key: The name of the key used for joining (i.e the key corresponding to value provided in the file).
        :param inputfile: A two column (e.g transcript_id and new value) file.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> join_file = get_example_file("simple", "join_mat")[0]
        >>> b_gtf = a_gtf.add_attr_from_matrix_file(feat="gene", key="gene_id", inputfile=join_file)
        >>> assert b_gtf.extract_data("S1",as_list=True, no_na=True) == ['0.2322', '0.999', '0.5555']
        >>> assert b_gtf.extract_data("S2",as_list=True, no_na=True) == ['0.4', '0.6', '0.7']

        """

        message("Calling add_attr_from_matrix_file", type="DEBUG")

        if feat is None:
            feat = ",".join(self.get_feature_list(nr=True))

        if inputfile is None:
            raise GTFtkError("Need an input/join file.")

        if isinstance(inputfile, file):
            inputfile = inputfile.name

        id_to_val = defaultdict(lambda: defaultdict(list))

        for line_nb, line in enumerate(open(inputfile, "r")):

            line = chomp(line)

            if line_nb == 0:
                tokens = line.split("\t")

                if len(tokens) < 2:
                    raise GTFtkError(
                        "Found less than 2 columns. Is the file tabulated ?")
                key_names = tokens[1:]
            else:
                token = line.split("\t")

                if len(token) < 2:
                    raise GTFtkError(
                        "Unable to split the line. Is the file tabulated ?")
                if len(token[1:]) != len(key_names):
                    raise GTFtkError(
                        "The number of columns differ from the header")

                for i in range(len(key_names)):
                    id_to_val[key_names[i]][token[0]] += [token[i + 1]]

        for i in range(len(key_names)):
            message("Adding key " + key_names[i], type="DEBUG")
            tmp_file = make_tmp_file(prefix="add_attr_" + re.sub('[\W]+',
                                                                 '',
                                                                 key_names[i]),
                                     suffix=".txt")
            for k, v in id_to_val[key_names[i]].items():
                tmp_file.write(k + "\t" + "|".join(v) + "\n")

            tmp_file.close()

            if i == 0:
                new_data = self._dll.add_attributes(self._data,
                                                    feat,
                                                    key,
                                                    key_names[i],
                                                    tmp_file.name)

            else:
                new_data = self._dll.add_attributes(new_data,
                                                    feat,
                                                    key,
                                                    key_names[i],
                                                    tmp_file.name)

        return self._clone(new_data)

    def add_attr_from_list(self,
                           feat=None,
                           key="transcript_id",
                           key_value=[],
                           new_key="new_key",
                           new_key_value=[]):
        """Add key/value pairs to the GTF object.

        :param feat: The comma separated list of target feature. If None, all the features.
        :param key: The name of the key used for joining (e.g 'transcript_id').
        :param key_value: The values for the key (e.g ['tx_1', 'tx_2',...,'tx_n'])
        :param new_key: A name for the novel key.
        :param new_key_value: A name for the novel key (e.g ['val_tx_1', 'val_tx_2',...,'val_tx_n']).

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b_gtf = a_gtf.add_attr_from_list(feat="gene", key="gene_id", key_value=["G0001", "G0002"], new_key="coding_pot", new_key_value=["0.5", "0.8"])
        >>> assert b_gtf.extract_data(keys="coding_pot", as_list=True, no_na=True) == ['0.5', '0.8']
        >>> b_gtf = a_gtf.add_attr_from_list(feat="gene", key="gene_id", key_value=["G0002", "G0001"], new_key="coding_pot", new_key_value=["0.8", "0.5"])
        >>> assert b_gtf.extract_data(keys="coding_pot", as_list=True, no_na=True) == ['0.5', '0.8']
        >>> key_value = a_gtf.extract_data("transcript_id", no_na=True, as_list=True, nr=True)
        >>> b=a_gtf.add_attr_from_list(None, key="transcript_id", key_value=key_value, new_key="bla", new_key_value=[str(x) for x in range(len(key_value))])
        """

        message("Calling add_attr_from_list", type="DEBUG")

        if not isinstance(key_value, list) or not isinstance(
                new_key_value, list):
            raise GTFtkError("key_value and new_key_value should be lists.")

        if feat is None:
            feat = ",".join(self.get_feature_list(nr=True))

        if len(set(key_value)) != len(key_value):
            raise GTFtkError("Each key should appear once in key_value.")

        if len(key_value) != len(new_key_value):
            raise GTFtkError(
                "key_value and new_key_value should have the same length.")

        if len(key_value) == 0:
            raise GTFtkError(
                "Need some data to join.")

        tmp_file = make_tmp_file("add_attr", ".txt")

        for i, j in zip(key_value, new_key_value):
            tmp_file.write("\t".join([str(i), str(j)]) + "\n")
        tmp_file.close()

        new_data = self._dll.add_attributes(self._data,
                                            feat,
                                            key,
                                            new_key,
                                            tmp_file.name)

        return self._clone(new_data)

    def add_attr_from_dict(self,
                           feat="*",
                           key="transcript_id",
                           a_dict=None,
                           new_key="new_key"):
        """Add key/value pairs to the GTF object.

        :param feat: The comma separated list of target feature. If None, all the features.
        :param key: The name of the key used for joining (e.g 'transcript_id').
        :param a_dict: key and values will be used to call add_attr_from_file.
        :param new_key: A name for the novel key.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_dict = a_gtf.nb_exons()
        >>> a_gtf = a_gtf.add_attr_from_dict(feat="transcript", a_dict=a_dict, new_key="exon_nb")
        >>> b_dict = a_gtf.select_by_key("feature", "transcript").extract_data("transcript_id,exon_nb", as_dict_of_values=True)
        >>> assert a_dict['G0006T001'] == int(b_dict['G0006T001'])
        >>> assert a_dict['G0008T001'] == int(b_dict['G0008T001'])
        """

        message("Calling add_attr_from_dict", type="DEBUG")

        if len(a_dict) == 0:
            raise GTFtkError(
                "Need some data to join.")

        tmp_file = make_tmp_file("add_attr_from_dict", ".txt")

        for i, j in a_dict.items():
            if isinstance(j, list):
                j = ",".join([str(x) for x in j])
            tmp_file.write("\t".join([str(i), str(j)]) + "\n")
        tmp_file.close()

        new_data = self._dll.add_attributes(self._data,
                                            feat,
                                            key,
                                            new_key,
                                            tmp_file.name)

        return self._clone(new_data)

    def del_attr(self,
                 feat="*",
                 keys=None,
                 force=False):
        """Delete an attributes from the GTF file..

        :param feat: The target feature.
        :param keys: Comma separated list or list of target keys.
        :param force: If True, transcript_id and gene_id can be deleted.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import TAB
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert a_gtf.del_attr(keys="gene_id,exon_id,ccds_id", force=True).get_attr_list() == ['transcript_id']
        """

        message("Calling del_attr", type="DEBUG")

        if keys is None:
            raise GTFtkError("A key is required.")

        if not isinstance(keys, list):
            keys = keys.split(",")

        if not isinstance(feat, list):
            feat = feat.split(",")

        if not force:
            if "transcript_id" in keys or "gene_id" in keys:
                raise GTFtkError(
                    "transcript_id/gene_id can't be removed. Use force if required.")

        new_data = self._dll.del_attributes(self._data,
                                            ",".join(feat),
                                            ",".join(keys))

        return self._clone(new_data)

    def select_shortest_transcripts(self):
        """Select the shortest transcript of each gene. Note that the genomic
        boundaries for each gene could differ from that displayed by its
        associated transcripts. The gene features may be subsequently deleted
        using select_by_key.


        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        """

        message("Calling select_shortest_transcripts.", type="DEBUG")

        new_data = self._dll.select_transcript(self._data, 1)

        return self._clone(new_data)

    def select_longuest_transcripts(self):
        """Select the longuest transcript of each gene.
        The "gene" rows are returned in the results. Note that the genomic
        boundaries for each gene could differ from that displayed by its
        associated transcripts. The gene features may be subsequently deleted
        using select_by_key.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        """

        message("Calling select_longuest_transcripts.", type="DEBUG")

        new_data = self._dll.select_transcript(self._data, 2)

        return self._clone(new_data)

    def select_5p_transcript(self):
        """Select the most 5' transcript of each gene. Note that the genomic
        boundaries for each gene could differ from that displayed by its
        associated transcripts. The gene features may be subsequently deleted
        using select_by_key.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)

        """

        message("Calling select_5p_transcript.", type="DEBUG")

        new_data = self._dll.select_transcript(self._data, 3)

        return self._clone(new_data)

    def get_feature_size(self, ft_type="gene", feat_id=None):
        """Returns feature size as a dict.

        :param ft_type: The feature type (3rd column). Could be gene, transcript, exon, CDS...
        :param feat_id: the string used as feature identifier in the GTF. Could be gene_id, transcript_id, exon_id, CDS_id... By default it is computed as ft_type + '_id'

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> assert len(a_gtf.get_feature_size("exon", "exon_id")) == 25

        """
        message("Calling get_feature_size.", type="DEBUG")

        if feat_id is None:
            feat_id = ft_type + "_id"

        feat_size_dict = dict()

        new_data = self.select_by_key("feature", ft_type, 0)

        for i in new_data:
            feat_size_dict[i.get_attr_value(feat_id)[0]] = i.end - i.start

        # Free the pointer
        # self._dll.free(new_data._data)

        return feat_size_dict

    def write(self, output, add_chr=0, gc_off=True):
        """write the gtf to a file.

        :param output: A file object where the GTF has to be written.
        :param add_chr: whether to add 'chr' prefix to seqid before printing.
        :param gc_off: If True, shutdown the garbage collector before printing to avoid passing through free_gtf_data which can be time-consuming.

        :Example:

        >>> from pygtftk.utils import simple_line_count
        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.utils import make_tmp_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> b_file = make_tmp_file()
        >>> a_gtf.write(b_file)
        >>> assert simple_line_count(b_file) == 70

        """
        if gc_off:
            gc.disable()

        self._message("Writing a GTF ")

        if pygtftk.utils.ADD_CHR == 1:
            add_chr = 1

        if isinstance(output, list):
            output = output[0]

        if isinstance(output, str):
            if output == "-":
                output_str = "-"
            else:
                try:
                    output = open(output, "w")
                    output.close()
                except:
                    raise GTFtkError("Unable to open file %s" % output)
                output_str = output.name

        elif isinstance(output, file):
            if output.name != '<stdout>':
                output.close()
                output_str = output.name
            else:
                output_str = "-"

        else:
            try:
                if output.name != '<stdout>':
                    output.close()
                    output_str = output.name
                else:
                    output_str = "-"
            except:
                raise GTFtkError("Unknown file object.")
        if self._data != 0 or len(self) > 0:
            self._dll.print_gtf_data(self._data, output_str, add_chr)
        else:
            pass

        if output_str != "-":
            output.close()
        message("GTF written.")

    def get_sequences(self, genome=None, intron=False, rev_comp=True):
        """
        Returns a FASTA object from which various sequences can be retrieved.

        :param genome: The genome in fasta file.
        :param intron: Set to True to get also intronic regions. Required for some methods of the FASTA object.
        :param rev_comp: By default sequence for genes on minus strand are \
        reversed-complemented. Set to False to avoid default behaviour.

        :Example:


    >>> from pygtftk.utils import get_example_file
    >>> from pygtftk.gtf_interface import GTF
    >>> a_file = get_example_file("simple", "gtf")[0]
    >>> a_gtf = GTF(a_file)
    >>> genome_fa = get_example_file("simple", "fa")[0]
    >>> # No intron, reverse-complement
    >>> a_fa = a_gtf.get_sequences(genome_fa)
    >>> assert len(a_fa) == 15
    >>> a_dict = dict()
    >>> for i in a_fa: a_dict[i.header] = i.sequence
    >>> assert a_dict['>G0001_NA_G0001T001_chr1:125-138_+_mRNA'] == 'cccccgttacgtag'
    >>> assert a_dict['>G0008_NA_G0008T001_chr1:210-222_-_RC_mRNA'] ==  'catgcgct'
    >>> assert a_dict['>G0004_NA_G0004T001_chr1:65-76_+_mRNA'] == 'atctggcg'
    >>> # No intron, no reverse-complement
    >>> a_fa = a_gtf.get_sequences(genome_fa, rev_comp=False)
    >>> a_dict = dict()
    >>> for i in a_fa: a_dict[i.header] = i.sequence
    >>> assert a_dict['>G0001_NA_G0001T001_chr1:125-138_+_mRNA'] == 'cccccgttacgtag'
    >>> assert a_dict['>G0008_NA_G0008T001_chr1:210-222_-_mRNA'] ==  'agcgcatg'
    >>> assert a_dict['>G0004_NA_G0004T001_chr1:65-76_+_mRNA'] == 'atctggcg'
    >>> # Intron and Reverse-complement
    >>> a_fa = a_gtf.get_sequences(genome_fa, intron=True)
    >>> a_dict = dict()
    >>> for i in a_fa: a_dict[i.header] = i.sequence
    >>> assert a_dict['>G0008_NA_G0008T001_chr1:210-222_-_RC'] == 'catatggtgcgct'
    >>> assert a_dict['>G0004_NA_G0004T001_chr1:65-76_+'] == 'atctcaggggcg'
    >>> # Intron and no Reverse-complement
    >>> a_fa = a_gtf.get_sequences(genome_fa, intron=True, rev_comp=False)
    >>> a_dict = dict()
    >>> for i in a_fa: a_dict[i.header] = i.sequence
    >>> assert a_dict['>G0008_NA_G0008T001_chr1:210-222_-'] == 'agcgcaccatatg'
    >>> assert a_dict['>G0004_NA_G0004T001_chr1:65-76_+'] == 'atctcaggggcg'
        """

        message("Calling 'get_sequences' method.", type="DEBUG")

        intron = int(intron)
        rev_comp = int(rev_comp)

        if genome is not None:

            fasta = FASTA(self.fn,
                          self._dll.get_sequences(self._data,
                                                  genome,
                                                  intron,
                                                  rev_comp),
                          bool(intron),
                          bool(rev_comp))
            return fasta

        else:
            return None

    def to_bed(self,
               name=["gene_id"],
               sep="|",
               add_feature_type=False,
               more_name=[]):
        """Returns a Bedtool object (Bed6 format).

        :param name: The keys that should be used to computed the 'name' column.
        :param more_name: Additional text to add to the name (a list).
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id".
        :param add_feature_type: Add the feature type to the name.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bo = a_gtf.select_by_key("feature", "transcript").to_bed()
        >>> assert a_bo.field_count() == 6
        >>> assert len(a_bo) == 15
        >>> for i in a_bo: pass
        >>> a_bo = a_gtf.select_by_key("feature", "transcript").to_bed(name=['gene_id', 'transcript_id'])
        >>> for i in a_bo: pass
        >>> a_bo = a_gtf.select_by_key("feature", "transcript").to_bed(name=['gene_id', 'transcript_id'], sep="--")
        >>> for i in a_bo: pass

        """

        message("Calling 'to_bed' method.", type="DEBUG")

        tx_bed = make_tmp_file("to_bed", ".bed")

        if not add_feature_type:
            key_csv = "seqid,start,end,score,strand," + ",".join(name)
            for i in self.extract_data(key_csv, zero_based=True, nr=False):
                line = [i[0],
                        i[1],
                        i[2],
                        sep.join(i[5:] + more_name),
                        i[3],
                        i[4]]
                tx_bed.write("\t".join(line) + "\n")

        else:

            key_csv = "seqid,start,end,score,strand,feature," + ",".join(name)
            for i in self.extract_data(key_csv, zero_based=True, nr=False):
                line = [i[0],
                        i[1],
                        i[2],
                        sep.join(i[6:] + more_name + [i[5]]),
                        i[3],
                        i[4]]
                tx_bed.write("\t".join(line) + "\n")

        tx_bed.close()

        return BedTool(tx_bed.name)

    def get_5p_end(self,
                   feat_type="transcript",
                   name=["transcript_id"],
                   sep="|",
                   as_dict=False,
                   more_name=[],
                   one_based=False,
                   feature_name=None):
        """Returns a Bedtool object containing the 5' coordinates of selected
        features (Bed6 format) or a dict (zero-based coordinate).

        :param feat_type: The feature type.
        :param name: The key that should be used to computed the 'name' column.
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id".
        :param more_name: Additional text to add to the name (a list).
        :param as_dict: return the result as a dictionnary.
        :param one_based: if as_dict is requested, return coordinates in on-based format.
        :param feature_name: A feature name to be added to the 4th column.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.select_by_key("feature", "exon").get_5p_end(feat_type="exon")
        >>> assert len(a_bed) == 25
        >>> a_dict = a_gtf.select_by_key("feature", "exon").get_5p_end(feat_type="exon", name=["exon_id"], as_dict=True)
        >>> assert len(a_dict) == 25
        >>> a_dict = a_gtf.select_by_key("feature", "exon").get_5p_end(feat_type="exon", name=["exon_id", "transcript_id"], as_dict=True)
        >>> assert len(a_dict) == 25

        """

        message("Calling 'get_5p_end'.", type="DEBUG")

        tx_bed = make_tmp_file("TSS", ".bed")

        for i in self.select_by_key("feature", feat_type):
            name_list = i.get_attr_value(attr_name=name,
                                         upon_none='set_na')

            if not feature_name is not None:
                name_out = sep.join(name_list + more_name)
            else:
                name_out = sep.join(name_list + more_name + [feature_name])

            i.write_bed_5p_end(name=name_out,
                               outputfile=tx_bed)
        tx_bed.close()

        bed_obj = BedTool(tx_bed.name)

        if as_dict:

            dict_obj = dict()

            for i in bed_obj:
                if one_based:
                    dict_obj[i.name] = i.start + 1
                else:
                    dict_obj[i.name] = i.start

            return dict_obj

        return bed_obj

    def get_tss(self,
                name=["transcript_id"],
                sep="|",
                as_dict=False,
                more_name=[],
                one_based=False,
                feature_name=None):
        """Returns a Bedtool object containing the TSSs (Bed6 format) or a dict
        (zero-based coordinate).

        :param name: The key that should be used to computed the 'name' column.
        :param more_name: Additional text to add to the name (a list).
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id".
        :param as_dict: return the result as a dictionnary.
        :param one_based: if as_dict is requested, return coordinates in on-based format.
        :param feature_name: A feature name to be added to the 4th column.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.get_tss()
        >>> assert len(a_bed) == 15

        """

        return (self.get_5p_end(feat_type="transcript",
                                name=name,
                                more_name=more_name,
                                feature_name=feature_name,
                                sep=sep,
                                as_dict=as_dict,
                                one_based=one_based))

    def get_3p_end(self,
                   feat_type="transcript",
                   name=["transcript_id"],
                   sep="|",
                   as_dict=False,
                   more_name=[],
                   feature_name=None):
        """Returns a Bedtool object containing the 3' coordinates of selected
        features (Bed6 format) or a dict (zero-based coordinate).

        :param feat_type: The feature type.
        :param name: The key that should be used to computed the 'name' column.
        :param more_name: Additional text to add to the name (a list).
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id".
        :param as_dict: return the result as a dictionnary.
        :param feature_name: A feature name to be added to the 4th column.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.select_by_key("feature", "exon").get_3p_end(feat_type="exon")
        >>> assert len(a_bed) == 25
        >>> a_bed = a_gtf.select_by_key("feature", "exon").get_3p_end(feat_type="exon", name=["gene_id","exon_id"])
        >>> assert len(a_bed) == 25

        """
        message("Calling 'get_3p_end'.", type="DEBUG")

        tx_bed = make_tmp_file("TTS", ".bed")

        for i in self.select_by_key("feature", feat_type):
            name_list = i.get_attr_value(attr_name=name,
                                         upon_none='set_na')
            if not feature_name is not None:
                name_out = sep.join(name_list + more_name)
            else:
                name_out = sep.join(name_list + more_name + [feature_name])

            i.write_bed_3p_end(name=name_out,
                               outputfile=tx_bed)
        tx_bed.close()

        bed_obj = BedTool(tx_bed.name)

        if as_dict:

            dict_obj = dict()

            for i in bed_obj:
                dict_obj[i.name] = i.start

            return dict_obj

        return bed_obj

    def get_tts(self,
                name=["transcript_id"],
                sep="|",
                as_dict=False,
                more_name=[],
                feature_name=None
                ):
        """Returns a Bedtool object containing the TTSs (Bed6 format) or a dict
        (zero-based coordinate).

        :param name: The key that should be used to computed the 'name' column.
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id".
        :param as_dict: return the result as a dictionnary.
        :param more_name: Additional text to add to the name (a list).
        :param feature_name: A feature name to be added to the 4th column.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.get_tts()
        >>> assert len(a_bed) == 15

        """
        return (self.get_3p_end(feat_type="transcript",
                                name=name,
                                sep=sep,
                                more_name=more_name,
                                feature_name=feature_name,
                                as_dict=as_dict))

    def get_gn_to_tx(self,
                     ordered_5p=False,
                     as_dict_of_dict=False):
        """Returns a dict with genes as keys and the list of their associated transcripts
        as values.

        params ordered_5p: If True, returns transcript list ordered based on their TSS coordinates (5' to 3'). For ties, value are randomly picked.
        params as_dict_of_dict: If True, returns a dict of dict that maps gene_id to transcript_id and transcript_id to TSS numbering (1 for most 5', then 2...).

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file(datasetname="mini_real",ext="gtf.gz")[0]
        >>> a_gtf = GTF(a_file)
        >>> gn_2_tx = a_gtf.get_gn_to_tx(ordered_5p=True)
        >>> assert gn_2_tx['ENSG00000148337'][0:3] == ['ENST00000372948', 'ENST00000634901', 'ENST00000634501']
        >>> assert gn_2_tx['ENSG00000148339'][0:3]  == ['ENST00000373068', 'ENST00000373069', 'ENST00000373066']
        >>> assert gn_2_tx['ENSG00000148339'][5:]  == ['ENST00000472769', 'ENST00000445012', 'ENST00000466983']
        >>> gn_2_tx = a_gtf.get_gn_to_tx(as_dict_of_dict=True)
        >>> assert gn_2_tx['ENSG00000153885']['ENST00000587658'] == 1
        >>> assert gn_2_tx['ENSG00000153885']['ENST00000587559'] == 2
        >>> assert gn_2_tx['ENSG00000153885']['ENST00000430256'] == 8
        >>> assert gn_2_tx['ENSG00000153885']['ENST00000284006'] == gn_2_tx['ENSG00000153885']['ENST00000589786']
        >>> assert gn_2_tx['ENSG00000164587']['ENST00000407193'] == 1
        >>> assert gn_2_tx['ENSG00000164587']['ENST00000401695'] == 2
        >>> assert gn_2_tx['ENSG00000164587']['ENST00000519690'] == 3
        >>> assert gn_2_tx['ENSG00000105483']['ENST00000517510'] == gn_2_tx['ENSG00000105483']['ENST00000520007']
        """

        message("Getting gene to transcript mapping")
        my_dict = self.extract_data("gene_id,transcript_id",
                                    as_dict_of_merged_list=True,
                                    nr=True,
                                    no_na=True)

        if as_dict_of_dict:
            ordered_5p = True
            my_dict_of_dict = defaultdict(dict)
            message("Getting gene to transcript to TSS mapping")

        if not ordered_5p:
            return my_dict
        else:

            strand = self.get_gn_strand()
            tss = self.get_tss(as_dict=True)

            for gn_id in my_dict:
                tx_tss = []
                tx_list = my_dict[gn_id]
                for tx_id in tx_list:
                    tx_tss += [int(tss[tx_id])]
                if strand[gn_id] != "-":
                    my_dict[gn_id] = [x for y, x in sorted(zip(tx_tss, tx_list))]
                else:
                    my_dict[gn_id] = [x for y, x in sorted(zip(tx_tss, tx_list), reverse=True)]

            if as_dict_of_dict:
                for gn_id in my_dict:
                    tx_id_prev = None
                    for pos, tx_id in enumerate(my_dict[gn_id]):
                        if pos == 0:
                            tss_num = 1
                        else:
                            if strand[gn_id] == "-":
                                if tss[tx_id_prev] > tss[tx_id]:
                                    tss_num += 1
                            else:
                                if tss[tx_id_prev] < tss[tx_id]:
                                    tss_num += 1
                        my_dict_of_dict[gn_id][tx_id] = tss_num
                        tx_id_prev = tx_id

                return my_dict_of_dict
            else:
                return my_dict

    def get_intergenic(self,
                       chrom_file=None,
                       upstream=0,
                       downstream=0,
                       chr_list=None,
                       feature_name=None):
        """Returns a bedtools object containing the intergenic regions.

        :param chrom_file: file object pointing to a tabulated two-columns file. Chromosomes as column 1 and their sizes as column 2 (default: None)
        :param upstream: Extend transcript coordinates in 5' direction.
        :param downstream: Extend transcript coordinates in 3' direction.
        :param chr_list: a list of chromosome to restrict intergenic regions.
        :param feature_name: A feature name to be added to the 4th column.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> chr_info_path = get_example_file(ext="chromInfo")[0]
        >>> chr_info_file = open(chr_info_path, "r")
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.get_intergenic(chrom_file=chr_info_file)
        >>> assert len(a_bed) == 10

        """

        message("Calling 'get_intergenic'.", type="DEBUG")

        if not isinstance(chrom_file, file):
            raise GTFtkError('chrom_file should be a file object.')

        if not os.path.exists(chrom_file.name):
            raise GTFtkError('chrom_file could not be found.')

        gtf = self.select_by_key("feature",
                                 "transcript")

        tx_bo = gtf.to_bed(name=["gene_id",
                                 "transcript_id"]).slop(s=True,
                                                        l=upstream,
                                                        r=downstream,
                                                        g=chrom_file.name).cut([0, 1,
                                                                                2, 3,
                                                                                4, 5])

        if chr_list is None:
            chrom_file_bed = chrom_info_to_bed_file(chrom_file)
        else:
            chrom_file_bed = chrom_info_to_bed_file(chrom_file,
                                                    chr_list=chr_list)
        chrom_file_bo = BedTool(chrom_file_bed.name)
        chrom_file_bo = chrom_file_bo.subtract(tx_bo).sort()

        # for tracability
        region_bed = make_tmp_file("intergenic", ".bed")
        chrom_file_bo.saveas(region_bed.name)

        if feature_name is not None:
            tmp_file = make_tmp_file("intergenic", ".bed6")
            for i in chrom_file_bo:
                out_list = i[:3] + [feature_name, ".", "."]
                tmp_file.write("\t".join(out_list) + "\n")
            tmp_file.close()
            chrom_file_bo = BedTool(tmp_file.name)

        return chrom_file_bo

    def get_introns(self,
                    by_transcript=False,
                    name=['transcript_id', 'gene_id'],
                    sep='|',
                    intron_nb_in_name=False,
                    feat_name=False,
                    feat_name_last=False):
        """Returns a bedtools object containing the intronic regions.

        :param by_transcript: If false (default), merged genic regions with no exonic overlap are returned. Otherwise, the intronic regions corresponding to each transcript are returned (may contain exonic overlap).
        :param name: The list of ids that should be part of the 4th column of the bed file (if by_transcript is choosen).
        :param sep: The separator to be used for the name (if by_transcript is choosen).
        :param intron_nb_in_name: by default the intron number is added to the score column. If selected, write this information in the 'name' column of the bed file.
        :param feat_name: add the feature name ('intron') in the name column.
        :param feat_name_last: put feat_name in last position (but before intron_nb_in_name).

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.get_introns()
        >>> assert len(a_bed) == 7

        """

        message("Calling 'get_intron'.", type="DEBUG")

        if not by_transcript:

            exons_bo = self.select_by_key("feature",
                                          "exon").to_bed(name=["gene_id",
                                                               "transcript_id",
                                                               "exon_id"]).cut([0, 1,
                                                                                2, 3,
                                                                                4, 5])

            tx_bo = self.select_by_key("feature",
                                       "transcript").to_bed(name=["gene_id",
                                                                  "transcript_id"]).cut([0, 1,
                                                                                         2, 3,
                                                                                         4, 5])

            introns_bo = tx_bo.subtract(exons_bo).sort().merge()

            # for tracability
            introns_bed = make_tmp_file("Intronic_strict", ".bed")
            introns_bo.saveas(introns_bed.name)
        else:

            intron_bed = make_tmp_file("introns", ".bed")
            exon_starts = defaultdict(list)
            exon_ends = defaultdict(list)
            tx_list = []
            chr_list = []
            info_list = []
            strand_list = []

            ids = "feature,seqid,start,end,transcript_id,strand,"
            ids = ids + ",".join(name)

            for i in self.extract_data(ids):
                if i[0] == "exon":
                    if i[4] not in exon_starts:
                        tx_list += [i[4]]
                        chr_list += [i[1]]
                        strand_list += [i[5]]
                        if feat_name:
                            if feat_name_last:
                                info_list += [sep.join(i[6:] + ["intron"])]
                            else:
                                info_list += [sep.join(["intron"] + i[6:])]
                        else:
                            info_list += [sep.join(i[6:])]
                    exon_starts[i[4]] += [i[2]]
                    exon_ends[i[4]] += [i[3]]

            for tx_cur in exon_starts:
                exon_starts[tx_cur] = sorted(
                    [int(x) for x in exon_starts[tx_cur]])
                exon_ends[tx_cur] = sorted([int(x) for x in exon_ends[tx_cur]])

            for tx_cur, chr, info, strand in zip(tx_list, chr_list, info_list, strand_list):

                nb_introns = len(exon_ends[tx_cur]) - 1

                if strand == "+":
                    n = 1
                elif strand == "-":
                    n = nb_introns
                else:
                    continue

                for i in range(0, nb_introns):

                    if intron_nb_in_name:
                        out_list = [chr,
                                    str(exon_ends[tx_cur][i]),
                                    str(exon_starts[tx_cur][i + 1] - 1),
                                    sep.join([info] + [str(n)]),
                                    ".",
                                    strand]
                    else:
                        out_list = [chr,
                                    str(exon_ends[tx_cur][i]),
                                    str(exon_starts[tx_cur][i + 1] - 1),
                                    info,
                                    str(n),
                                    strand]
                    if strand == "+":
                        n += 1
                    elif strand == "-":
                        n -= 1

                    intron_bed.write("\t".join(out_list) + "\n")

            introns_bo = BedTool(intron_bed.name)

        return introns_bo

    def get_midpoints(self,
                      name=["transcript_id", "gene_id"],
                      sep="|"):
        """Returns a bedtools object containing the midpoints of features.

        :param name: The key that should be used to computed the 'name' column.
        :param sep: The separator used for the name (e.g 'gene_id|transcript_id')".

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_bed = a_gtf.select_by_key("feature", "exon").get_midpoints()
        >>> assert len(a_bed) == 25

        """

        message("Calling 'get_midpoints'.", type="DEBUG")

        midpoints_bed = make_tmp_file("Midpoints", ".bed")

        # Select all lines and dump them into a bed file
        bed_obj = self.to_bed(name,
                              sep=sep).sort()
        for line in bed_obj:

            diff = line.end - line.start

            if diff % 2 != 0:
                # e.g 10-13 (zero based) -> 11-13 one based
                # mipoint is 12 (one-based) -> 11-12 (zero based)
                # e.g 949-1100 (zero based) -> 950-1100 one based
                # mipoint is 1025 (one-based) -> 1024-1025 (zero based)
                # floored division (python 2)...
                line.end = line.start + int(diff / 2) + 1
                line.start = line.end - 1
            else:
                # e.g 10-14 (zero based) -> 11-14 one based
                # mipoint is 12-13 (one-based) -> 11-13 (zero based)
                # e.g 9-5100 (zero based) -> 10-5100 one based
                # mipoint is 2555-2555 (one-based) -> 2554-2555 (zero based)
                # floored division (python 2)...
                # No real center. Take both

                line.start = line.start + int(diff / 2) - 1
                line.end = line.start + 2

            midpoints_bed.write(str(line))

        midpoints_bed.close()

        return BedTool(midpoints_bed.name)

    def get_tx_ids(self, nr=False):
        """Returns all transcript_id from the GTF file

        :param nr: True to get a non redondant list.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> tx_ids = a_gtf.get_tx_ids()
        >>> assert len(tx_ids) == 70
        >>> tx_ids = a_gtf.get_tx_ids(nr=True)
        >>> assert len(tx_ids) == 15
        >>> a_gtf = GTF(a_file).select_by_key("transcript_id","G0001T002,G0001T001,G0003T001")
        >>> tx_ids = a_gtf.get_tx_ids(nr=True)
        >>> assert len(tx_ids) == 3

        """

        tx_ids = []

        message("Calling 'get_tx_ids'.", type="DEBUG")

        if not nr:
            tab = self.extract_data("transcript_id")
            for i in tab:
                tx_ids += [i[0]]
        else:
            tab = self.extract_data("transcript_id,feature")
            for i in tab:
                if i[1] == 'transcript':
                    tx_ids += [i[0]]

        return tx_ids

    def get_gn_ids(self, nr=False):
        """Returns all gene ids from the GTF file

        :param nr: True to get a non redondant list.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> gn_ids = a_gtf.get_gn_ids()
        >>> assert len(gn_ids) == 70
        >>> gn_ids = a_gtf.get_gn_ids(nr=True)
        >>> assert len(gn_ids) == 10
        >>> a_gtf = GTF(a_file).select_by_key("gene_id","G0001,G0002")
        >>> gn_ids = a_gtf.get_gn_ids(nr=True)
        >>> assert len(gn_ids) == 2

        """

        message("Calling 'get_gn_ids'.", type="DEBUG")

        alist = list()

        tab = self.extract_data(keys="gene_id")

        if nr:
            d = dict()
            adict = defaultdict(lambda: 0, d)

            for i in tab:
                if i[0] not in adict:
                    alist += [i[0]]
                    adict[i[0]] = 1
        else:
            for i in tab:
                alist += [i[0]]

        return alist

    def get_feature_list(self, nr=False):
        """Returns the list of features.

        :param nr: True to get a non redondant list.

        :Example:

        >>> from pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_gtf = GTF(a_file)
        >>> a_feat = a_gtf.get_feature_list(nr=True)
        >>> assert len(a_feat) == 4
        >>> a_feat = a_gtf.get_feature_list(nr=False)
        >>> assert len(a_feat) == 70

        """

        message("Calling 'get_feature_list'.", type="DEBUG")

        alist = list()

        tab = self.extract_data(keys="feature")

        if nr:
            d = dict()
            adict = defaultdict(lambda: 0, d)

            for i in tab:
                if i[0] not in adict:
                    alist += [i[0]]
                    adict[i[0]] = 1
        else:
            for i in tab:
                alist += [i[0]]

        return alist

    def get_chroms(self, nr=False, as_dict=False):
        """Returns the chomosome/sequence ID from the GTF.

        :param nr: True to get a non redondant list.
        :param as_dict: True to get info as a dict.


        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_file = get_example_file()[0]
        >>> a_chr = GTF(a_file).get_chroms(nr=True)
        >>> assert len(a_chr) == 1
        >>> a_chr = GTF(a_file).get_chroms()
        >>> assert len(a_chr) == 70

        """

        message("Calling 'get_chroms'.", type="DEBUG")

        if as_dict:
            alist = OrderedDict()
            ptr = self._dll.get_seqid_list(self._data)
            for i in range(ptr.size):
                key = ffi.string(ptr.data[i][1])
                val = ffi.string(ptr.data[i][0])
                alist[key] = val
        else:
            if nr:
                alist = list()
                ptr = self._dll.get_seqid_list(self._data)
                for i in range(ptr.size):
                    alist += [ffi.string(ptr.data[i][1])]
            else:
                alist = list()
                tab = self.extract_data(keys="seqid")
                for i in tab:
                    alist += [i[0]]

        return alist

    def get_transcript_size(self, with_intron=False):
        """Returns a dict with transcript_id as keys and their mature RNA length
        (i.e exon only) of each transcript.

        :param with_intron: If True, add intronic regions.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> a_path = get_example_file()[0]
        >>> gtf = GTF(a_path)
        >>> size_dict = gtf.get_transcript_size()
        >>> assert(size_dict["G0008T001"] == 8)
        >>> size_dict = gtf.get_transcript_size(with_intron=True)
        >>> assert(size_dict["G0008T001"] == 13)

        """

        message("Calling 'get_transcript_size'.", type="DEBUG")

        d = dict()
        tx_size = defaultdict(lambda: 0, d)

        tab = self.extract_data(keys="feature,transcript_id,start,end")

        if not with_intron:

            for i in tab:
                if i[0] == "exon":
                    tx_size[i[1]] += int(i[3]) - int(i[2]) + 1
        else:
            for i in tab:
                if i[0] == "transcript":
                    tx_size[i[1]] = int(i[3]) - int(i[2]) + 1

        return tx_size

    def add_attr_column(self, input_file=None, new_key="new_key"):
        """Simply add a new column of attribute/value to each line.

        :param input_file: a single column file with nrow(GTF_DATA) lines. File lines should be sorted according to the GTF_DATA object. Lines for which a new key should not be added should contain ".".
        :param new_key: name of the novel key.

        :Example:

        >>> from  pygtftk.utils import get_example_file
        >>> from pygtftk.gtf_interface import GTF
        >>> from pygtftk.utils import make_tmp_file
        >>> from pygtftk.utils import NEWLINE
        >>> a_path = get_example_file()[0]
        >>> gtf = GTF(a_path)
        >>> tmp_file =  make_tmp_file()
        >>> for i in range(len(gtf)): tmp_file.write(str(i) + NEWLINE)
        >>> tmp_file.close()
        >>> gtf = gtf.add_attr_column(tmp_file, new_key='foo')
        >>> a_list = gtf.extract_data('foo', as_list=True)
        >>> assert [int(x) for x in a_list] == range(70)


        """

        if isinstance(input_file, str):
            input_file = open(input_file)

        if input_file.closed:
            input_file = open(input_file.name, "r")

        tmp = input_file.readlines()

        if len(tmp) != len(self):
            raise GTFtkError(
                "The number of lines to add should be the same as the number of lines in the GTF.")

        for line in tmp:
            if "\t" in line:
                raise GTFtkError("input_file should contain only one column.")

        new_data = self._dll.add_attr_column(
            self._data,
            input_file.name,
            new_key)

        return self._clone(new_data)


if __name__ == "__main__":

    from pygtftk.utils import get_example_file
    from pygtftk.gtf_interface import GTF

    a = get_example_file()
    gtf = GTF(a[0])
    for i in gtf["feature", "transcript"]:
        i.write(sys.stdout)