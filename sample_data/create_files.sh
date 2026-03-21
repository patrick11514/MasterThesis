#!/bin/bash

# THIS SCRIPT WILL CREATE RANDOM FILES IN SOME FOLDER STRUCTURE TO TEST NIGHT CLASSIFYING

FILE="2026-02-28_23-37-06__-19.90_60.00s_0433.fits"

mkdir -p "NIGHTS"

for i in {1..10}
do
    mkdir -p "NIGHTS/OBJECT_$i"
    for j in {1..10}
    do
        mkdir -p "NIGHTS/OBJECT_$i/Session_2026_02-$j"
        cp "$FILE" "NIGHTS/OBJECT_$i/Session_2026_02-$j/$(basename "$FILE")"
    done
done