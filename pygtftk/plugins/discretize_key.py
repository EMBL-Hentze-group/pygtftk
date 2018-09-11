#!/usr/bin/env python
from __future__ import division
from __future__ import print_function

import argparse
import os
import sys

import numpy as np
import pandas

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.arg_formatter import int_greater_than_null
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import make_tmp_file
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

    if len([x for x in src_values if x not in ['.', '?']]) == 0:
        message('The key was not found in this GTF.',
                type="ERROR")

    min_val = None
    max_val = None

    dest_values = []
    dest_pos = []

    for p, v in enumerate(src_values):
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

            dest_values += [a]
            dest_pos += [p]
        except:
            pass

    if min_val is None:
        message("Did not find numeric values in the source key.",
                type="ERROR")
    if min_val == max_val:
        message("The minimum and maximum values found in the source key are the same.",
                type="ERROR")

    if log:
        if 0 in dest_values:
            message("Encountered zero values before log transformation.",
                    type="WARNING",
                    force=True)
            message("Adding a pseudocount (+1).",
                    type="WARNING",
                    force=True)

            pseudo_count = 1
            dest_values = list(np.log2([x + pseudo_count for x in dest_values]))

        # update max/min values
        max_val = max(dest_values)
        min_val = min(dest_values)

    # Apply the same rule as pandas.cut when bins is an int.
    min_val = min_val - max_val / 1000

    # -------------------------------------------------------------------------
    #
    # Compute percentiles if required
    #
    # -------------------------------------------------------------------------

    if percentiles:
        if percentiles_of_uniq:
            dest_values_tmp = [min_val] + list(set(dest_values))
        else:
            dest_values_tmp = [min_val] + dest_values
        n = nb_levels

        q = [
            np.percentile(
                dest_values_tmp,
                100 /
                n *
                i) for i in range(
                0,
                n)]
        q = q + [np.percentile(dest_values_tmp, 100)]

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

        breaks = pandas.cut(dest_values,
                            bins=q,
                            labels=labels
                            )
    else:
        breaks = pandas.cut(dest_values,
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

    tmp_file = make_tmp_file(prefix="discretized_keys", suffix=".txt")

    with tmp_file as tp_file:
        for p, v in zip(dest_pos, breaks):
            tmp_file.write(str(p) + "\t" + str(v) + '\n')

    gtf.add_attr_to_pos(tmp_file,
                        new_key=dest_key).write(outputfile,
                                                gc_off=True)

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
              fun=os.path.abspath(__file__),
              updated=__updated__,
              desc=__doc__,
              notes=__notes__,
              group="editing",
              test=test)
