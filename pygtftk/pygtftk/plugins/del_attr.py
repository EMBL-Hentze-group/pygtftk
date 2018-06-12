#!/usr/bin/env python
from __future__ import print_function

import argparse
import re
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import message

__updated__ = "2018-01-20"
__doc__ = """
 Delete one or several attributes from the gtf file.
"""
__notes__ = """
 -- You may also use 'complex' regexp such as : "(^.*_id$|^.*_biotype$)"
 -- Example: gtftk get_example -d mini_real | gtftk del_attr -k "(^.*_id$|^.*_biotype$)" -r -v
"""


def make_parser():
    parser = argparse.ArgumentParser(add_help=True)

    parser_grp = parser.add_argument_group('Arguments')

    parser_grp.add_argument('-i', '--inputfile',
                            help="Path to the GTF file. Default to STDIN",
                            default=sys.stdin,
                            metavar="GTF",
                            type=FileWithExtension('r',
                                                   valid_extensions='\.[Gg][Tt][Ff](\.[Gg][Zz])?$'))

    parser_grp.add_argument('-o', '--outputfile',
                            help="Output file.",
                            default=sys.stdout,
                            metavar="GTF",
                            type=FileWithExtension('w',
                                                   valid_extensions='\.[Gg][Tt][Ff]$'))

    parser_grp.add_argument('-k', '--key',
                            help='Comma separated list of attribute names or a '
                                 'regular expression (see -r).',
                            default=None,
                            metavar="KEY",
                            type=str,
                            required=True)

    parser_grp.add_argument('-r', '--reg-exp',
                            help='The key name is a regular expression.',
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-v', '--invert-match',
                            help='Delected keys are those not matching any of'
                                 ' the specified key.',
                            action="store_true",
                            required=False)

    return parser


def del_attr(
        inputfile=None,
        outputfile=None,
        key="transcript_id",
        reg_exp=False,
        invert_match=False,
        tmp_dir=None,
        logger_file=None,
        verbosity=0):
    """
    Delete extended attributes in the target gtf file. attr_list can be a
    comma-separated list of attributes.
    """

    gtf = GTF(inputfile, check_ensembl_format=False)

    if reg_exp:
        try:
            rgxp = re.compile(key)
        except:
            message("Check the regular expression please.", type="ERROR")
        key_list = [key]
    else:
        key_list = key.split(",")

    for i in gtf:

        feature_keys = i.get_attr_names()

        if not invert_match:
            for k in key_list:
                if not reg_exp:
                    try:
                        del i.attr[k]
                    except:
                        pass
                else:
                    for feat_key in feature_keys:
                        if rgxp.search(feat_key):
                            del i.attr[feat_key]
        else:

            for k in feature_keys:
                if not reg_exp:
                    if k not in key_list:
                        del i.attr[k]
                else:
                    if not rgxp.search(k):
                        del i.attr[k]

        i.write(outputfile)

    close_properly(outputfile, inputfile)


if __name__ == '__main__':
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    del_attr(**args)

else:

    test = """

    #del_attr:
    # If you delete almost all extended attributes there are only exon_id left
    @test "del_attr_1" {
     result=`gtftk del_attr -i pygtftk/data/simple/simple.gtf  -k ccds_id,transcript_id,gene_id| cut -f9| grep -v "^$"| sed 's/ \".*//'| sort | uniq`
      [ "$result" = "exon_id" ]
    }
    
    
    #del_attr: check -v
    @test "del_attr_1" {
     result=`gtftk del_attr -i pygtftk/data/simple/simple.gtf  -k ccds_id,transcript_id,gene_id -v| grep exon_id| wc -l`
      [ "$result" -eq 0 ]
    }
    
    """

    CmdObject(name="del_attr",
              message="Delete attributes in the target gtf file.",
              parser=make_parser(),
              fun=del_attr,
              updated=__updated__,
              notes=__notes__,
              desc=__doc__,
              group="editing",
              test=test)