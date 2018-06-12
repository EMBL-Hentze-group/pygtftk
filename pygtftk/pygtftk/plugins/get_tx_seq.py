#!/usr/bin/env python
from __future__ import print_function

import argparse
import re
import shutil
import sys

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.arg_formatter import globbedFileList
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import message, make_tmp_file

__updated__ = "2018-01-20"
__doc__ = """
 Get transcripts sequences in a flexible fasta format from a GTF file.
"""
__notes__ = """
 -- The sequences are returned in 5' to 3' orientation.
 -- If you want to use wildcards, use quotes :e.g. 'foo/bar*.fa'.
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
                            help="Output FASTA file.",
                            default=sys.stdout,
                            metavar="FASTA",
                            type=FileWithExtension('w',
                                                   valid_extensions=('\.[Ff][Aa][Ss][Tt][Aa]$',
                                                                     '\.[Ff][Aa]$')))

    parser_grp.add_argument('-g', '--genome',
                            help="The genome in fasta format. Accept path with wildcards (e.g. *.fa).",
                            default=None,
                            metavar="FASTA",
                            action=globbedFileList,
                            required=True)

    parser_grp.add_argument('-w', '--with-introns',
                            help="Set to true to include intronic regions.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-s', '--separator',
                            help="To separate info in header.",
                            default="|",
                            type=str,
                            metavar="SEP",
                            required=False)

    parser_grp.add_argument('-l', '--label',
                            help="A set of key for the header.",
                            default="feature,transcript_id,gene_id,seqid,start,end",
                            type=str,
                            required=False)

    parser_grp.add_argument('-f', '--sleuth-format',
                            help="Produce output in sleuth format.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-d', '--delete-version',
                            help="In case of --sleuth-format, delete gene_id or transcript_id version number (e.g '.2' in ENSG56765.2).",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-a', '--assembly',
                            help="In case of --sleuth-format, an assembly version.",
                            default="GRCm38",
                            type=str,
                            required=False)

    parser_grp.add_argument('-c', '--del-chr',
                            help="When using --sleuth-format delete 'chr' in sequence id.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-n', '--no-rev-comp',
                            help="Don't reverse complement sequence "
                                 "corresponding to gene on minus strand.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-e', '--explicit',
                            help="Write explicitly the name of the keys in the header.",
                            action="store_true",
                            required=False)

    return parser


def get_tx_seq(inputfile=None,
               outputfile=None,
               genome=None,
               with_introns=False,
               delete_version=False,
               del_chr=False,
               separator="",
               no_rev_comp=False,
               label="",
               sleuth_format=True,
               explicit=True,
               assembly="bla",
               tmp_dir=None,
               logger_file=None,
               verbosity=0):
    """
    Description: Get transcripts sequences in fasta format from a GTF file.
    """

    # -----------------------------------------------------------
    #  Check chromosomes in fasta file
    # -----------------------------------------------------------

    genome_chr_list = []

    message("%d fasta files found." % len(genome))

    if len(genome) == 1:
        message("Checking fasta file chromosome list")
        genome = genome[0]
        with genome as genome_file:
            for i in genome_file:
                if i.startswith(">"):
                    i = i.rstrip("\n")
                    genome_chr_list += [i[1:]]
    else:
        message("Merging fasta files")
        tmp_genome = make_tmp_file(prefix="genome", suffix=".fa")
        with tmp_genome as tg:
            for curr_file in genome:
                message("Merging %s" % curr_file.name)
                with curr_file as cf:
                    shutil.copyfileobj(cf, tg, 1024 * 1024 * 100)

        message("Checking fasta file chromosome list")
        genome = open(tmp_genome.name, "r")
        with genome as genome_file:
            for i in genome_file:
                if i.startswith(">"):
                    i = i.rstrip("\n")
                    genome_chr_list += [i[1:]]

    rev_comp = not no_rev_comp

    message("Chromosomes in fasta file: " + ",".join(genome_chr_list))

    # -----------------------------------------------------------
    #  Read gtf
    # -----------------------------------------------------------

    gtf = GTF(inputfile)
    nb_tx_before = gtf.extract_data("transcript_id",
                                    as_list=True,
                                    no_na=True,
                                    nr=True)

    # -----------------------------------------------------------
    #  Select genes falling in chrom defined in the fasta file
    # -----------------------------------------------------------

    message("Chromosomes in gtf file: " + ",".join(gtf.get_chroms(nr=True)))

    message("Selecting chromosome defined in the fasta file")

    gtf = gtf.select_by_key(key="seqid",
                            value=",".join(genome_chr_list))

    message("Chromosomes in gtf file: " + ",".join(gtf.get_chroms(nr=True)))

    if len(gtf) == 0:
        message("No genes were found on chromosomes defined in fasta file.",
                type="ERROR")

    nb_tx_after = gtf.extract_data("transcript_id",
                                   as_list=True,
                                   no_na=True,
                                   nr=True)
    if len(nb_tx_after) != len(nb_tx_before):
        diff = list(set(nb_tx_before) - set(nb_tx_after))
        message("Some transcripts had"
                " no corresponding chromosome"
                " in the fasta file: " + ",".join(diff)[0:100] + "...")

    message("Using genome file: " + genome.name)
    message("Retrieving fasta sequences from " + genome.name)
    fasta_seq = gtf.get_sequences(genome=genome.name,
                                  intron=with_introns,
                                  rev_comp=rev_comp)

    tx_gtf = gtf.select_by_key("feature", "transcript")

    if sleuth_format:

        tx_biotype = tx_gtf.extract_data("transcript_id,transcript_biotype",
                                         as_dict_of_lists=True)
        gn_biotype = tx_gtf.extract_data("gene_id,gene_biotype",
                                         as_dict_of_lists=True)

        for i in fasta_seq:
            gene_id = i.gene_id
            transcript_id = i.transcript_id
            chrom = i.chrom

            gn_bio = gn_biotype[i.gene_id][0]
            tx_bio = tx_biotype[i.transcript_id][0]

            if delete_version:
                transcript_id = re.sub('\.[0-9]+$', '', transcript_id)
                gene_id = re.sub('\.[0-9]+$', '', gene_id)
            if del_chr:
                chrom = chrom.replace('chr', '')

            header = " ".join([transcript_id,
                               ":".join(["chromosome",
                                         assembly, chrom,
                                         str(i.start), str(i.end), "1"]),
                               "gene:" + gene_id,
                               "gene_biotype:" + gn_bio,
                               "transcript_biotype:" + tx_bio])

            outputfile.write(">" + header + "\n")
            outputfile.write(i.sequence + "\n")
    else:
        tx_info = tx_gtf.extract_data("transcript_id," + label,
                                      as_dict_of_lists=True)
        for i in fasta_seq:
            if not explicit:
                header = separator.join(tx_info[i.transcript_id])
            else:
                header = [str(x[0]) + "=" + x[1]
                          for x in zip(label.split(","), tx_info[i.transcript_id])]
                header = separator.join(header)
            outputfile.write(">" + header + "\n")
            outputfile.write(i.sequence + "\n")

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    get_tx_seq(**args)


if __name__ == '__main__':
    main()


else:

    test = """
   
    #get_tx_seq: test a mono-exonic tx (- strand)
    @test "get_tx_seq_1" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa | grep G0008T001 -A 1| tail -1`
      [ "$result" = "catgcgct" ]
    }
    
    #get_tx_seq: test a bi-exonic transcript (- strand) with rev-comp
    @test "get_tx_seq_2" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf --no-rev-comp -g pygtftk/data/simple/simple.fa | grep G0008T001 -A 1| tail -1`
      [ "$result" = "agcgcatg" ]
    }
    
       
    #get_tx_seq: test a bi-exonic transcript (- strand) with  --no-rev-comp and --introns
    @test "get_tx_seq_3" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -n -w|  grep G0008T001 -A 1| tail -1`
      [ "$result" = "agcgcaccatatg" ]
    }
    
    #get_tx_seq: test a bi-exonic transcript (- strand) with --introns
    @test "get_tx_seq_4" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -w|  grep G0008T001 -A 1| tail -1`
      [ "$result" = "catatggtgcgct" ]
    }
    
    #get_tx_seq: test a bi-exonic transcript (- strand) with --introns
    @test "get_tx_seq_5" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -w |  grep G0008T001 -A 1| tail -1`
      [ "$result" = "catatggtgcgct" ]
    }
 
    #get_tx_seq: test a bi-exonic transcript (- strand) with --introns --no-rev-comp
    @test "get_tx_seq_6" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -w -n|  grep G0008T001 -A 1| tail -1`
      [ "$result" = "agcgcaccatatg" ]
    }
    
    # The sequence is independant of exon order
    #get_tx_seq: test a bi-exonic transcript (- strand) with --introns --no-rev-comp
    @test "get_tx_seq_7" {
     result=`gtftk get_example |  perl -MList::Util -e 'print List::Util::shuffle <>' > /tmp/get_example_shuf.gtf ; gtftk get_tx_seq -i /tmp/get_example_shuf.gtf -g pygtftk/data/simple/simple.fa| grep G0006T001  -A 1 | tail -1`
      [ "$result" = "gctattacat" ]
    }

    #sleuth output
    @test "get_tx_seq_8" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -f| wc -l`
      [ "$result" -eq 30 ]
    }

    #sleuth output
    @test "get_tx_seq_9" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -f| head -1`
      [ "$result" = ">G0001T002 chromosome:GRCm38:chr1:125:138:1 gene:G0001 gene_biotype:. transcript_biotype:." ]
    }

    #sleuth output
    @test "get_tx_seq_10" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -f -a bla| head -1`
      [ "$result" = ">G0001T002 chromosome:bla:chr1:125:138:1 gene:G0001 gene_biotype:. transcript_biotype:." ]
    }

    # The process ends normality if no corresponding chr is found
    @test "get_tx_seq_11" {
     result=`sed 's/^/bla/' pygtftk/data/simple/simple.gtf | gtftk get_tx_seq -g pygtftk/data/simple/simple.fa | wc -l `
      [ "$result" -eq 0 ]
    }
    
    # The process ends normality if no corresponding chr is found
    @test "get_tx_seq_12" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -l chrom,start,end| head -1`
      [ "$result" = ">chr1|125|138" ]
    }
        
    # The process ends normality if no corresponding chr is found
    @test "get_tx_seq_13" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -l transcript_id,gene_id,gene_biotype| head -1`
      [ "$result" = ">G0001T002|G0001|." ]
    }

    # The process ends normality if no corresponding chr is found
    @test "get_tx_seq_14" {
     result=`gtftk get_tx_seq -i pygtftk/data/simple/simple.gtf -g pygtftk/data/simple/simple.fa -l feature,transcript_id,seqid -s , | head -1 `
      [ "$result" = ">transcript,G0001T002,chr1" ]
    }
        
    """

    CmdObject(name="get_tx_seq",
              message="Get transcript sequences in fasta format.",
              parser=make_parser(),
              fun=get_tx_seq,
              group="sequences",
              desc=__doc__,
              notes=__notes__,
              test=test)