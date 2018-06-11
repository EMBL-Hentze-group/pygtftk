#!/usr/bin/env python
from __future__ import division
from __future__ import print_function

import argparse
import sys

import numpy as np
import pandas

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.arg_formatter import int_greater_than_null
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import message

__updated__ = "2018-01-20"
__doc__ = """
 Create a new key by discretizing a numeric key. This can be helpful to create new classes
 on the fly that can be used subsequently.
"""

__notes__ = """
 -- if -\-ft-type is not set the destination key will be assigned to all feature containing
 the source key.
 -- Non-numeric value for source key will be translated into 'NA'.
 -- The default is to create equally spaced interval. The interval can also be created by computing the percentiles (-p).
 
"""


def make_parser():
    """The program parser."""
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

    parser_grp.add_argument('-k', '--src-key',
                            help='The name of the source key',
                            default=None,
                            type=str,
                            required=True)

    parser_grp.add_argument('-d', '--dest-key',
                            help='The name of the target key.',
                            default=None,
                            type=str,
                            required=True)

    parser_grp.add_argument('-n', '--nb-levels',
                            help='The number of levels/classes to create.',
                            default=2,
                            metavar="KEY",
                            type=int_greater_than_null,
                            required=True)

    parser_grp.add_argument('-t', '--ft-type',
                            help="A target feature (as found in the 3rd column of the GTF).",
                            default=None,
                            type=str,
                            required=False)

    parser_grp.add_argument('-l', '--labels',
                            help="A comma separated list of labels of size --nb-levels.",
                            default=None,
                            type=str,
                            required=False)

    parser_grp.add_argument('-p', '--percentiles',
                            help="Compute --nb-levels classes using percentiles.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-g', '--log',
                            help="Compute breaks based on log-scale.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-u', '--percentiles-of-uniq',
                            help="Compute percentiles based on non-redondant values.",
                            action="store_true",
                            required=False)

    return parser


def discretize_key(inputfile=None,
                   outputfile=None,
                   src_key=None,
                   dest_key=None,
                   nb_levels=None,
                   percentiles=False,
                   percentiles_of_uniq=False,
                   log=False,
                   ft_type=None,
                   labels=None,
                   tmp_dir=None,
                   logger_file=None,
                   verbosity=0):
    """
    Create a new key by discretizing a numeric key.
    """

    if nb_levels < 2:
        message("--nb-levels has to be greater than 2.",
                type="ERROR")

    # -------------------------------------------------------------------------
    #
    # Check labels and nb_levels
    #
    # -------------------------------------------------------------------------

    if labels is not None:
        labels = labels.split(",")
        if len(labels) != nb_levels:
            message("The number of labels should be the same as the number of levels.",
                    type="ERROR")
        if len(labels) != len(set(labels)):
            message("Redundant labels not allowed.", type="ERROR")

    # -------------------------------------------------------------------------
    #
    # Load GTF. Retrieve values for src-key
    #
    # -------------------------------------------------------------------------

    gtf = GTF(inputfile, check_ensembl_format=False)
    src_values = gtf.extract_data(src_key, as_list=True)

    if len([x for x in src_values if x != '.']) == 0:
        message('The key was not found in this GTF.',
                type="ERROR")

    if ft_type is not None:
        feat_values = gtf.extract_data("feature", as_list=True)

    min_val = None
    max_val = None

    numeric_val = []

    for v in src_values:
        try:
            a = float(v)
            if min_val is not None:
                if a > max_val:
                    max_val = a
                if a < min_val:
                    min_val = a
            else:
                min_val = a
                max_val = a

            numeric_val += [a]
        except:
            pass

    if min_val is None:
        message("Did not find numeric values in the source key.",
                type="ERROR")
    if min_val == max_val:
        message("The minimum and maximum values found in the source key are the same.",
                type="ERROR")

    if log:
        if 0 in numeric_val:
            message("Encountered zero values.",
                    type="WARNING",
                    force=True)
            message("Adding a pseudocount (+1).",
                    type="WARNING",
                    force=True)

            pseudo_count = 1
        else:
            pseudo_count = 0

        numeric_val = list(np.log2([x + pseudo_count for x in numeric_val]))
        max_val = max(numeric_val)
        min_val = min(numeric_val)

    # Apply the same rule as pandas.cut when bins is an int.
    min_val = min_val - max_val / 1000

    # -------------------------------------------------------------------------
    #
    # Compute percentiles if required
    #
    # -------------------------------------------------------------------------

    if percentiles:
        if percentiles_of_uniq:
            numeric_val_tmp = [min_val] + list(set(numeric_val))
        else:
            numeric_val_tmp = [min_val] + numeric_val
        n = nb_levels
        q = [
            np.percentile(
                numeric_val_tmp,
                100 /
                n *
                i) for i in range(
                0,
                n)]
        q = q + [np.percentile(numeric_val_tmp, 100)]

        if len(q) != len(set(q)):
            message("No ties are accepted in  percentiles :",
                    type="WARNING",
                    force=True)
            message("Breaks: " + str(q), type="WARNING", force=True)
            message("Try -u. Exiting", type="ERROR")

    # -------------------------------------------------------------------------
    #
    # Create a factor
    #
    # -------------------------------------------------------------------------

    if percentiles:

        breaks = pandas.cut(numeric_val,
                            bins=q,
                            labels=labels
                            )
    else:
        breaks = pandas.cut(numeric_val,
                            bins=nb_levels,
                            labels=labels
                            )
    # The string can be very problematic later...
    breaks.categories = [str(x).replace(", ", "_") for x in breaks.categories]

    message("Categories: " + str(list(breaks.categories)),
            type="INFO",
            force=True)

    # -------------------------------------------------------------------------
    #
    # Write to disk
    #
    # -------------------------------------------------------------------------

    nb_numeric = 0
    nb_line = 0

    if ft_type is None:
        for line in gtf:
            if src_values[nb_line] == ".":

                line.write(outputfile)
            else:

                line.add_attr_and_write(dest_key,
                                        breaks[nb_numeric],
                                        outputfile)
                nb_numeric += 1
            nb_line += 1

    else:
        for line in gtf:
            if src_values[nb_line] == ".":
                line.write(outputfile)
            else:
                if feat_values[nb_line] == ft_type:
                    line.add_attr_and_write(dest_key,
                                            breaks[nb_numeric],
                                            outputfile)
                nb_numeric += 1

            nb_line += 1

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    discretize_key(**args)


if __name__ == '__main__':
    main()

else:

    test = """
    # discretize_key
    @test "discretize_key_1" {
     result=`gtftk join_attr -i pygtftk/data/simple/simple.gtf  -j pygtftk/data/simple/simple.join_mat -k gene_id -m | gtftk discretize_key -k S1 -d S1_d -n 2 -V 2 -l A,B  | gtftk tabulate  -k S1_d -Hun| perl -npe 's/\\n/,/'`
      [ "$result" = "A,B," ]
    }

    # discretize_key
    @test "discretize_key_2" {
     result=`gtftk join_attr -i pygtftk/data/simple/simple.gtf  -j pygtftk/data/simple/simple.join_mat -k gene_id -m | gtftk discretize_key -k S1 -d S1_d -n 3 -V 2  | gtftk tabulate  -k S1_d -Hun| perl -npe 's/\\n/,/'`
      [ "$result" = "(0.231_0.488],(0.743_0.999],(0.488_0.743]," ]
    }


    # discretize_key
    @test "discretize_key_3" {
     result=`gtftk join_attr -i pygtftk/data/simple/simple.gtf  -j pygtftk/data/simple/simple.join_mat -k gene_id -m | gtftk discretize_key -k S1 -d S1_d -n 2 -V 2  | gtftk tabulate  -k S1_d -Hun| perl -npe 's/\\n/,/'`
      [ "$result" = "(0.231_0.616],(0.616_0.999]," ]
    }

   """

    CmdObject(name="discretize_key",
              message="Create a new key through discretization of a numeric key.",
              parser=make_parser(),
              fun=discretize_key,
              updated=__updated__,
              desc=__doc__,
              notes=__notes__,
              group="editing",
              test=test)
