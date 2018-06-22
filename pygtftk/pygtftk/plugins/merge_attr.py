#!/usr/bin/env python
from __future__ import print_function

import argparse
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly

__updated__ = "2018-01-20"
__doc__ = """
 Merge a set of attributes into a destination attribute. Can be
 useful, for instance, to merge gene_name and gene_id values into 
 a new key to prepare the GTF for RNA-seq quantification.
"""

__notes__ = """
-- The destination key can be one of the source key, leading to an update of that key.
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
                            help='Comma separated list of keys to join.',
                            default=None,
                            metavar="KEY",
                            type=str,
                            required=True)

    parser_grp.add_argument('-d', '--dest-key',
                            help='The target key name.',
                            default=None,
                            metavar="KEY",
                            type=str,
                            required=True)

    parser_grp.add_argument('-s', '--separator',
                            help="The separator for the concatenated values.",
                            default="|",
                            metavar="SEP",
                            type=str)

    parser_grp.add_argument('-f', '--target-feature',
                            help='The name of the target feature.',
                            default="*",
                            type=str,
                            required=False)
    return parser


def merge_attr(
        inputfile=None,
        outputfile=None,
        src_key="gene_id,transcript_id",
        separator="|",
        target_feature="*",
        dest_key="gene_tx_ids",
        tmp_dir=None,
        logger_file=None,
        verbosity=None):
    """
    Merge a set of attributes into a destination attribute.
    """

    gtf = GTF(inputfile,
              check_ensembl_format=False
              ).merge_attr(target_feature,
                           src_key,
                           dest_key,
                           separator).write(outputfile)

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    merge_attr(**args)


if __name__ == '__main__':
    main()


else:
    test = """
   
    #merge_attr: check basic args.
    @test "merge_attr_1" {
     result=`gtftk get_example | gtftk merge_attr -k transcript_id,gene_id -d gene_tx_concat|gtftk tabulate -H -k gene_tx_concat|grep G0009T001| sort | uniq`
      [ "$result" = "G0009T001|G0009" ]
    }

    @test "merge_attr_2" {
     result=`gtftk get_example | gtftk merge_attr -k transcript_id,gene_id -d gene_tx_concat -f transcript| gtftk select_by_key -k feature -v exon| gtftk tabulate -k gene_tx_concat -H | sort | uniq`
      [ "$result" = "." ]
    }

    @test "merge_attr_3" {
     result=`gtftk get_example | gtftk merge_attr -k transcript_id,gene_id -d gene_tx_concat -f transcript| gtftk select_by_key -k feature -v transcript| gtftk tabulate -k gene_tx_concat -H | sort | uniq | wc -l`
      [ "$result" -eq 15 ]
    }
    
    @test "merge_attr_4" {
     result=`gtftk get_example -d mini_real | gtftk merge_attr -k end,start,transcript_id,gene_id -d gene_tx_concat -f transcript| gtftk select_by_key -k feature -v transcript| wc -l`
      [ "$result" -eq 8531 ]
    }
    
    @test "merge_attr_5" {
     result=`gtftk get_example -d mini_real | gtftk merge_attr -k end,start,transcript_id,gene_id -d gene_tx_concat -f exon| gtftk select_by_key -k feature -v exon| wc -l`
      [ "$result" -eq 64251 ]
    }
    """
    msg = "Merge a set of attributes into a destination attribute."
    CmdObject(name="merge_attr",
              message=msg,
              parser=make_parser(),
              fun=merge_attr,
              group="editing",
              updated=__updated__,
              notes=__notes__,
              desc=__doc__,
              test=test)