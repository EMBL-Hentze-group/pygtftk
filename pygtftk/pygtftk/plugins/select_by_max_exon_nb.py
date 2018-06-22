#!/usr/bin/env python
from __future__ import print_function

import argparse
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import message

__updated__ = "2018-02-11"
__doc__ = """
For each gene select the transcript with the highest number of exons.
"""


def make_parser():
    """The program parser."""
    parser = argparse.ArgumentParser(add_help=True)

    parser.add_argument('-i', '--inputfile',
                        help="Path to the GTF file. Default to STDIN",
                        default=sys.stdin,
                        metavar="GTF",
                        type=FileWithExtension('r',
                                               valid_extensions='\.[Gg][Tt][Ff](\.[Gg][Zz])?$'))

    parser.add_argument('-o', '--outputfile',
                        help="Output file.",
                        default=sys.stdout,
                        metavar="GTF",
                        type=FileWithExtension('w',
                                               valid_extensions='\.[Gg][Tt][Ff]$'))

    return parser


def select_by_max_exon_nb(inputfile=None,
                          outputfile=None,
                          tmp_dir=None,
                          logger_file=None,
                          verbosity=0):
    """
    Select transcripts based on the number of exons.
    """

    msg = "Selecting transcript with the highest number of exon for each gene."
    message(msg)

    gtf = GTF(inputfile,
              check_ensembl_format=False
              ).select_by_max_exon_nb()

    gtf.write(outputfile)


def main():
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    select_by_max_exon_nb(**args)


if __name__ == '__main__':
    main()


else:

    test = """
    #select_by_max_exon_nb
    @test "select_by_max_exon_nb_1" {
     result=`gtftk get_example  -d simple_04 | gtftk select_by_max_exon_nb | grep G0005T001 | wc -l`
      [ "$result" -eq 0 ]
    }

    #select_by_max_exon_nb
    @test "select_by_max_exon_nb_2" {
     result=`gtftk get_example  -d simple_04 | gtftk select_by_max_exon_nb | grep G0004T002 | wc -l`
      [ "$result" -eq 0 ]
    }
    
    #select_by_max_exon_nb
    @test "select_by_max_exon_nb_3" {
     result=`gtftk get_example  -d simple_04 | gtftk select_by_max_exon_nb | grep G0006T002 | wc -l`
      [ "$result" -eq 0 ]
    }
    
    """

    CmdObject(name="select_by_max_exon_nb",
              message="For each gene select the transcript with the highest number of exons.",
              parser=make_parser(),
              fun=select_by_max_exon_nb,
              group="selection",
              updated=__updated__,
              desc=__doc__,
              test=test)