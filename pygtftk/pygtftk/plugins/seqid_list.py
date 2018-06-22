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
 Select the seqid/chromosomes
"""


def make_parser():
    """The parser."""
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
                            metavar="TXT",
                            type=FileWithExtension('w',
                                                   valid_extensions=('\.[Tt][Xx][Tt]',
                                                                     '\.[Cc][Ss][Vv]',
                                                                     '\.[Tt][Aa][Bb]',
                                                                     '\.[Tt][Ss][Vv]')))

    parser_grp.add_argument('-s', '--separator',
                            help="The separator to be used for separating key names.",
                            default="\n",
                            metavar="SEP",
                            type=str)

    return parser


def seqid_list(
        inputfile=None,
        outputfile=None,
        tmp_dir=None,
        separator="",
        logger_file=None,
        verbosity=0):
    """
    Select the seqid/chromosomes.
    """

    for i in GTF(inputfile, check_ensembl_format=False).get_chroms(nr=True):
        outputfile.write(str(i) + separator)

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    count(**args)


if __name__ == '__main__':
    main()

else:

    test = """

    @test "seqid_list_1" {
     result=`gtftk get_example -d mini_real | gtftk seqid_list | wc -l`
      [ "$result" -eq 23 ]
    }

    @test "seqid_list_2" {
     result=`gtftk get_example -d mini_real | gtftk seqid_list -s ","`
      [ "$result" = "chr1,chr10,chr11,chr12,chr13,chr14,chr15,chr16,chr17,chr18,chr19,chr2,chr20,chr21,chr22,chr3,chr4,chr5,chr6,chr7,chr8,chr9,chrX," ]
    }
    """

    CMD = CmdObject(name="seqid_list",
                    message="Returns the chromosome list.",
                    parser=make_parser(),
                    fun=seqid_list,
                    updated=__updated__,
                    desc=__doc__,
                    group="information",
                    test=test)