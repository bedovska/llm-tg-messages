#!/usr/bin/env bash

set -euo pipefail

if (( $# < 1 || $# > 2 )); then
    echo "Usage: $0 PROMPT_FOLDER [x100|x1000]" >&2
    exit 1
fi

prompt_folder=$1
dataset_size=${2:-x100}

if [[ $dataset_size != "x100" && $dataset_size != "x1000" ]]; then
    echo "Dataset size must be x100 or x1000: $dataset_size" >&2
    exit 1
fi

if [[ ! -d $prompt_folder ]]; then
    echo "Prompt folder not found: $prompt_folder" >&2
    exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
prompt_folder=$(cd "$prompt_folder" && pwd)
results_folder="$prompt_folder/results"

shopt -s nullglob
input_files=("$repo_root/data/test/${dataset_size}-"*.csv)

if (( ${#input_files[@]} == 0 )); then
    echo "No ${dataset_size} test files found in $repo_root/data/test" >&2
    exit 1
fi

mkdir -p "$results_folder"

for input_file in "${input_files[@]}"; do
    dataset_name=$(basename "$input_file" .csv)
    output_file="$results_folder/$dataset_name.jsonl"

    if [[ -f $output_file ]]; then
        echo "Skipping $dataset_name: result already exists at $output_file"
        continue
    fi

    echo "Processing $dataset_name"
    python "$repo_root/scripts/process_messages.py" process \
        --input_file="$input_file" \
        --output_file="$output_file" \
        --prompt_folder="$prompt_folder"

    python "$repo_root/scripts/count_token_usage.py" \
        --input_file="$output_file"
done
