#!/bin/bash
# Outputs the age in seconds of the most recent mnemosyne session entry.
LATEST=$(docker exec chn-quickstart-mongodb-1 mongosh mnemosyne --quiet --eval \
  "db.session.find({},{timestamp:1,_id:0}).sort({timestamp:-1}).limit(1).forEach(d=>print(d.timestamp.getTime()))" \
  2>/dev/null)

if [ -z "$LATEST" ]; then
    echo "error: could not query mnemosyne"
    exit 1
fi

NOW_MS=$(date +%s%3N)
AGE_S=$(( (NOW_MS - LATEST) / 1000 ))
echo "${AGE_S}"
