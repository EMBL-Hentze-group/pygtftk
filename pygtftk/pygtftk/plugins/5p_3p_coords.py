#!/usr/bin/env python
from __future__ import print_function

__updated__ = "2018-01-20"
__doc__ = """
 Get the 5p or 3p coordinate for each feature (e.g TSS or TTS for a transcript).
"""
__notes__ = "Output is in BED format."

import sys
import argparse
from pygtftk.gtf_interface import GTF
from pygtftk.utils import message
from pygtftk.utils import close_properly
from pygtftk.utils import write_properly
from pygtftk.utils import chomp
from pygtftk.cmd_object import CmdObject
from pygtftk.arg_formatter import FileWithExtension


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

    return parser


def get_5p_3p_coord(
        inputfile=None,
        outputfile=None,
        ft_type="transcript",
        names="transcript_id",
        separator="|",
        more_names='',
        transpose=0,
        invert=False,
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
                                 more_name=more_names)

    else:

        bed_obj = gtf.get_3p_end(feat_type=ft_type,
                                 name=nms,
                                 sep=separator,
                                 more_name=more_names)

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
    get_5p_3p_coord(**args)


if __name__ == '__main__':
    main()

else:

    test = """

    #5p_3p_coord: -v
    @test "5p_3p_coord_1" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf -v | cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "115,137,185,188,2,209,21,27,32,49,75," ]
    }
    
    #5p_3p_coord: no arg
    @test "5p_3p_coord_2" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf | cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "106,124,13,175,179,221,34,46,60,64," ]
    }
    
    #5p_3p_coord: -t gene
    @test "5p_3p_coord_3" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf -t gene| cut -f2| sort| uniq| perl -npe 's/\\n/,/'`
      [ "$result" = "106,124,13,175,179,221,34,46,60,64," ]
    }
    
    #5p_3p_coord: -t exon
    @test "5p_3p_coord_4" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf -t exon| wc -l`
      [ "$result" -eq 25 ]
    }
    
    #5p_3p_coord: -t gene
    @test "5p_3p_coord_5" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf -t gene| wc -l`
      [ "$result" -eq 10 ]
    }
    
    #5p_3p_coord: -t transcript
    @test "5p_3p_coord_6" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf -t transcript| wc -l`
      [ "$result" -eq 15 ]
    }
    
    #5p_3p_coord: nb column
    @test "5p_3p_coord_7" {
     result=`gtftk 5p_3p_coord  -i pygtftk/data/simple/simple.gtf | awk '{print NF}' | sort | uniq`
      [ "$result" -eq 6 ]
    }
    
    #5p_3p_coord: test stdin
    @test "5p_3p_coord_8" {
     result=`cat pygtftk/data/simple/simple.gtf| gtftk  5p_3p_coord | wc -l`
      [ "$result" -eq 15 ]
    }

    #5p_3p_coord: test transpose
    @test "5p_3p_coord_9" {
     result=`gtftk get_example| gtftk  5p_3p_coord -p 10| head -1 | cut -f 2`
      [ "$result" -eq 134 ]
    }

    #5p_3p_coord: test transpose
    @test "5p_3p_coord_10" {
     result=`gtftk get_example| gtftk  5p_3p_coord -p 10| head -4| tail -n 1  | cut -f 2`
      [ "$result" -eq 50 ]
    }

    """
    CmdObject(name="5p_3p_coord",
              message="Get the 5p or 3p coordinate for each feature. TSS or TTS for a transcript.",
              parser=make_parser(),
              fun=get_5p_3p_coord,
              notes=__notes__,
              updated=__updated__,
              desc=__doc__,
              group="coordinates",
              test=test)