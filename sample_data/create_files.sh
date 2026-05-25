#!/bin/bash

# THIS SCRIPT WILL CREATE RANDOM FILES IN SOME FOLDER STRUCTURE TO TEST NIGHT CLASSIFYING

FILE="2026-02-28_23-37-06__-19.90_60.00s_0433.fits"

mkdir -p "NIGHTS"

OBJECT_MAP=(
    "NGC_1234"
    "M31"
    "M42"
    "NGC_5678"
    "M51"
    "M101"
    "NGC_9101"
    "M87"
    "M104"
    "NGC_1122"
)

for obj in "${OBJECT_MAP[@]}"
do
    mkdir -p "NIGHTS/Object ${obj}"
    
    for j in {01..10}
    do
        mkdir -p "NIGHTS/Object ${obj}/Session 2026_02-${j}"
        cp "$FILE" "NIGHTS/Object ${obj}/Session 2026_02-${j}/$(basename "$FILE")"
    done
done
