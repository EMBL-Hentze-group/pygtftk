#!/usr/bin/env python
from __future__ import print_function

import argparse
import os
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly

__updated__ = "2018-01-20"
__doc__ = """
 Count the number of each features in the gtf file.
"""


def make_parser():
    """The parser."""
    parser = argparse.ArgumentParser(add_help=True)

    parser_grp = parser.add_argument_group('Arguments')

    parser_grp.add_argument('-i', '--inputfile',
                            help="Path to the GTF file. Default to STDIN.",
                            default=sys.stdin,
                            metavar="GTF",
                            required=False,
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
                                                                     '\.[Tt][Ss][Vv]',
                                                                     '\.[Cc][Oo][Vv]')))

    parser_grp.add_argument('-d', '--header',
                            help="A comma-separated list of string to use as header.",
                            default=None,
                            type=str,
                            required=False)

    parser_grp.add_argument('-t', '--additional-text',
                            help="A facultative text to be printed in the third "
                                 "column (e.g species name).",
                            default=None,
                            metavar="TEXT",
                            type=str,
                            required=False)

    return parser


def count(
        inputfile=None,
        outputfile=None,
        header=None,
        additional_text=None,
        tmp_dir=None,
        logger_file=None,
        verbosity=0):
    """
    Count the number of features in the gtf file.
    """

    if header is not None:
        header = header.split(",")

    gtf = GTF(inputfile, check_ensembl_format=False)

    feat_nb = dict()

    for i in gtf.extract_data("feature"):
        i = i[0]
        if feat_nb.get(i, None) is not None:
            feat_nb[i] += 1
        else:
            feat_nb[i] = 1

    if header is not None:
        outputfile.write("\t".join(header) + "\n")

    for i in feat_nb:
        if additional_text is None:
            outputfile.write(i + "\t" + str(feat_nb[i]) + "\n")
        else:
            outputfile.write(i + "\t" + str(feat_nb[i]) + "\t" +
                             additional_text + "\n")
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

    #count
    @test "count_1" {
     result=`gtftk get_example  | gtftk count| grep exon| cut -f2 `
      [ "$result" -eq 25 ]
    }
    
    #count: number of genes = 10
    @test "count_2" {
     result=`gtftk get_example | gtftk count| grep gene| cut -f2 `
      [ "$result" -eq 10 ]
    }
    
    #count: number of features = 4
    @test "count_3" {
     result=`gtftk get_example | gtftk count -t toto | cut -f3 | grep toto | wc -l`
      [ "$result" -eq 4 ]
    }

    #count: test additional args
    @test "count_4" {
     result=`gtftk get_example | gtftk count  -d feature,count,text -t species| cut -f2| perl -npe 's/\\n/,/'`
      [ "$result" = "count,25,10,15,20," ]
    }

    #count: test additional args
    @test "count_5" {
     result=`gtftk get_example | gtftk count  -d feature,count,text -t species| cut -f3| perl -npe 's/\\n/,/'`
      [ "$result" = "text,species,species,species,species," ]
    }
    #count: test additional args
    @test "count_6" {
     result=`gtftk get_example | gtftk count  -d feature,count,text -t species| cut -f1| perl -npe 's/\\n/,/'`
      [ "$result" = "feature,exon,gene,transcript,CDS," ]
    }

    """

    CMD = CmdObject(name="count",
                    message="Count the number of features in the gtf file.",
                    parser=make_parser(),
                    fun=os.path.abspath(__file__),
                    updated=__updated__,
                    desc=__doc__,
                    group="information",
                    test=test)
