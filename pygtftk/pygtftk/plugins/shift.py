#!/usr/bin/env python
"""

"""
from __future__ import print_function

import argparse
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.arg_formatter import chromFileAsDict
from pygtftk.cmd_object import CmdObject
from pygtftk.error import GTFtkError
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly

__updated__ = "2018-01-20"
__doc__ = """
 Transpose coordinates in 3' or 5' direction.
"""
__notes__ = """
 -- By default shift is not strand specific. Meaning that if -\shift-value is set to 10, all coordinates will be moved 10 bases in 5' direction relative to the forward/watson/plus/top strand.
 -- Use a negative value to shift in 3' direction, a positive value to shift in 5' direction.
 -- If -\stranded is true, features are transposed in 5' direction relative to their associated strand.
 -- By default, features are not allowed to go outside the genome coordinates. In the current implementation, in case this would happen (using a very large -\shift-value), feature would accumulate at the ends of chromosomes irrespectively of gene or transcript structures giving rise, ultimately, to several exons from the same transcript having the same starts or ends. 
 -- One can forced features to go outside the genome and ultimatly dissapear with large -\shift-value by using -a.
"""


def make_parser():
    """The program CLI."""
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

    parser_grp.add_argument('-s', '--shift-value',
                            help="Shift coordinate by s nucleotides.",
                            default=0,
                            type=int,
                            required=True)

    parser_grp.add_argument('-d', '--stranded',
                            help="By default shift not .",
                            action="store_true")

    parser_grp.add_argument('-a', '--allow-outside',
                            help="Accept the partial or total disappearance of a feature upon shifting.",
                            action="store_true")

    parser_grp.add_argument('-c', '--chrom-info',
                            help="Tabulated two-columns file. Chromosomes"
                                 " as column 1 and sizes as"
                                 " column 2 ",
                            default=None,
                            metavar="CHROMINFO",
                            action=chromFileAsDict,
                            required=True)

    return parser


def shift(inputfile=None,
          outputfile=None,
          shift_value=None,
          tmp_dir=None,
          chrom_info=None,
          stranded=False,
          allow_outside=False,
          logger_file=None,
          verbosity=0):
    """Shift coordinates in 3' or 5' direction.
    """

    gtf = GTF(inputfile, check_ensembl_format=False)

    chrom_list_gtf = gtf.get_chroms(nr=True)

    for chr in chrom_list_gtf:
        if chr not in chrom_info:
            raise GTFtkError("Chromosome " + chr + " was not found in chrom-info file.")

    for i in gtf:
        size = i.end - i.start + 1
        if not stranded:
            new_start = i.start + shift_value
            new_end = i.end + shift_value
        else:
            if i.strand == "-":
                new_start = i.start - shift_value
                new_end = i.end - shift_value
            else:
                new_start = i.start + shift_value
                new_end = i.end + shift_value

        # Feature is going outside genome in left direction
        if not allow_outside:
            if new_start < 1:
                new_start = 1
                new_end = size

            # Feature is going outside genome in right direction
            if new_end > int(chrom_info[i.chrom]):
                new_end = int(chrom_info[i.chrom])
                new_start = new_end - size + 1
        else:
            if new_start < 1:
                new_start = 1
                if new_end < 1:
                    new_end = None

            # Feature is going outside genome in right direction
            if new_end > int(chrom_info[i.chrom]):
                new_end = int(chrom_info[i.chrom])
                if new_start > int(chrom_info[i.chrom]):
                    new_start = None

        if new_start is not None and new_end is not None:
            i.start = new_start
            i.end = new_end
            i.write(outputfile)

    close_properly(outputfile, inputfile)


def main():
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    shift(**args)


if __name__ == '__main__':
    main()

else:

    test = '''
    #shift
    @test "shift_1" {
     result=`gtftk get_example|  gtftk shift -s -10 -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 4`
      [ "$result" -eq 115 ]
    }
    
    #shift
    @test "shift_2" {
     result=`gtftk get_example|  gtftk shift -s -10 -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 5`
      [ "$result" -eq 128 ]
    }

    #shift
    @test "shift_3" {
     result=`gtftk get_example|  gtftk shift -s 10 -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 4`
      [ "$result" -eq 135 ]
    }

    #shift
    @test "shift_4" {
     result=`gtftk get_example|  gtftk shift -s 10 -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 5`
      [ "$result" -eq 148 ]
    }


    #shift
    @test "shift_5" {
     result=`gtftk get_example|  gtftk shift -s -10 -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 5`
      [ "$result" -eq 128 ]
    }

    #shift
    @test "shift_5" {
     result=`gtftk get_example|  gtftk shift -s -10 -d -c pygtftk/data/mini_real/hg38.genome | head -n 1| cut -f 5`
      [ "$result" -eq 128 ]
    }


    '''

    cmd = CmdObject(name="shift",
                    message="Transpose coordinates.",
                    parser=make_parser(),
                    fun=shift,
                    desc=__doc__,
                    group="coordinates",
                    updated=__updated__,
                    notes=__notes__,
                    test=test)