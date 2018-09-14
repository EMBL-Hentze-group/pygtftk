#!/usr/bin/env python
from __future__ import print_function

import argparse
import os
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import chomp
from pygtftk.utils import close_properly
from pygtftk.utils import message
from pygtftk.utils import write_properly

__updated__ = "2018-01-20"
__doc__ = """
 Get the 5p or 3p coordinate for each feature (e.g TSS or TTS for a transcript).
"""
__notes__ = "Output is in BED format."


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
                            help="Output file (BED).",
                            default=sys.stdout,
                            metavar="BED",
                            type=FileWithExtension('w',
                                                   valid_extensions=('\.[Bb][Ee][Dd]$',
                                                                     '\.[Bb][Ee][Dd]6$')))

    parser_grp.add_argument('-t', '--ft-type',
                            help="The target feature (as found in the 3rd "
                                 "column of the GTF).",
                            default='transcript',
                            type=str,
                            required=False)

    parser_grp.add_argument('-v', '--invert',
                            help="Get 3' coordinate.",
                            action="store_true")

    parser_grp.add_argument('-p', '--transpose',
                            help="Transpose coordinate in 5' (use negative value) or in 3' (use positive values).",
                            type=int,
                            required=False,
                            default=0)

    parser_grp.add_argument('-n', '--names',
                            help="The key(s) that should be used as name.",
                            default="gene_id,transcript_id",
                            metavar="NAME",
                            type=str)

    parser_grp.add_argument('-m', '--more-names',
                            help="A comma separated list of information to be added to the 'name' column of the bed file.",
                            default=None,
                            type=str)

    parser_grp.add_argument('-s', '--separator',
                            help="The separator to be used for separating name elements (see -n).",
                            default="|",
                            metavar="SEP",
                            type=str)

    parser_grp.add_argument('-e', '--explicit',
                            help="Write explicitly the name of the keys in the header.",
                            action="store_true",
                            required=False)
    return parser


def get_5p_3p_coords(inputfile=None,
                     outputfile=None,
                     ft_type="transcript",
                     names="transcript_id",
                     separator="|",
                     more_names='',
                     transpose=0,
                     invert=False,
                     explicit=False,
                     tmp_dir=None,
                     logger_file=None,
                     verbosity=0):
    """
    Get the 5p or 3p coordinate for each feature (e.g TSS or TTS for a transcript).
    """

    if more_names is None:
        more_names = []
    else:
        more_names = more_names.split(',')

    if not invert:
        message("Computing 5' coordinates of '" + ft_type + "'.")
    else:
        message("Computing 3' coordinates of '" + ft_type + "'.")

    nms = names.split(",")

    gtf = GTF(inputfile, check_ensembl_format=False)

    if not invert:

        bed_obj = gtf.get_5p_end(feat_type=ft_type,
                                 name=nms,
                                 sep=separator,
                                 more_name=more_names,
                                 explicit=explicit)

    else:

        bed_obj = gtf.get_3p_end(feat_type=ft_type,
                                 name=nms,
                                 sep=separator,
                                 more_name=more_names,
                                 explicit=explicit)

    if not len(bed_obj):
        message("Requested feature could not be found. Use convert_ensembl maybe.",
                type="ERROR")

    if transpose == 0:
        for i in bed_obj:
            write_properly(chomp(str(i)), outputfile)
    else:
        for i in bed_obj:
            out_list = list()
            if i.strand == "+":
                out_list = [i.chrom,
                            str(i.start + transpose),
                            str(i.end + transpose),
                            i.name,
                            i.score,
                            i.strand]
            elif i.strand == "-":
                out_list = [i.chrom,
                            str(i.start - transpose),
                            str(i.end - transpose),
                            i.name,
                            i.score,
                            i.strand]
            outputfile.write("\t".join(out_list) + "\n")

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    get_5p_3p_coords(**args)


if __name__ == '__main__':
    main()

else:

    test = """

    #get_5p_3p_coords: -v
    @test "get_5p_3p_coords_1" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf -v | cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "115,137,185,188,2,209,21,27,32,49,75," ]
    }
    
    #get_5p_3p_coords: no arg
    @test "get_5p_3p_coords_2" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf | cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "106,124,13,175,179,221,34,46,60,64," ]
    }
    
    #get_5p_3p_coords: -t gene
    @test "get_5p_3p_coords_3" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf -t gene| cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "106,124,13,175,179,221,34,46,60,64," ]
    }
    
    #get_5p_3p_coords: -t exon
    @test "get_5p_3p_coords_4" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf -t exon| wc -l`
      [ "$result" -eq 25 ]
    }
    
    #get_5p_3p_coords: -t gene
    @test "get_5p_3p_coords_5" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf -t gene| wc -l`
      [ "$result" -eq 10 ]
    }
    
    #get_5p_3p_coords: -t transcript
    @test "get_5p_3p_coords_6" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf -t transcript| wc -l`
      [ "$result" -eq 15 ]
    }
    
    #get_5p_3p_coords: nb column
    @test "get_5p_3p_coords_7" {
     result=`gtftk get_5p_3p_coords  -i pygtftk/data/simple/simple.gtf | awk '{print NF}' | sort | uniq`
      [ "$result" -eq 6 ]
    }
    
    #get_5p_3p_coords: test stdin
    @test "get_5p_3p_coords_8" {
     result=`cat pygtftk/data/simple/simple.gtf| gtftk  get_5p_3p_coords | wc -l`
      [ "$result" -eq 15 ]
    }

    #get_5p_3p_coords: test transpose
    @test "get_5p_3p_coords_9" {
     result=`gtftk get_example| gtftk  get_5p_3p_coords -p 10| head -1 | cut -f 2`
      [ "$result" -eq 134 ]
    }

    #get_5p_3p_coords: test transpose
    @test "get_5p_3p_coords_10" {
     result=`gtftk get_example| gtftk  get_5p_3p_coords -p 10| head -4| tail -n 1  | cut -f 2`
      [ "$result" -eq 50 ]
    }

    #get_5p_3p_coord: test transpose
    @test "get_5p_3p_coords_11" {
     result=`gtftk get_example| gtftk  get_5p_3p_coords -p 10 -e -m bla -n transcript_id,gene_id,gene_name| head -1 | cut -f4`
      [ "$result" = "transcript_id=G0001T002|gene_id=G0001|gene_name=.|more_name=bla" ]
    }
    
    
    
    """
    CmdObject(name="get_5p_3p_coords",
              message="Get the 5p or 3p coordinate for each feature. TSS or TTS for a transcript.",
              parser=make_parser(),
              fun=os.path.abspath(__file__),
              notes=__notes__,
              updated=__updated__,
              desc=__doc__,
              group="coordinates",
              test=test)