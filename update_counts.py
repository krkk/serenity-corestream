#!/usr/bin/env python3

import datetime
import json
import os
import subprocess
import time

SERENITY_DIR = "serenity/"
FILENAME_JSON = "tagged_history.json"
FILENAME_CSV = "tagged_history.csv"
FILENAME_CACHE = "cache.json"
# Save the cache only every X commits, instead of after every commit.
SAVE_CACHE_INV_FREQ = 50

CORE_STREAM_REGEX = "Core::Stream"
CORE_FILE_REGEX = "(CFile|Core::File)([&>]|::(open|construct))" # there's also try_create() from C_OBJECT macro but thank god nobody used it
AK_STREAM_REGEX = "(Input|Output|(Circular|)Duplex|Constrained|Reconsumable)(Bit|File|Memory|)Stream"
C_FILE_REGEX = "fopen\\(|fdopen\\(|FILE\\*" # not accounting for stdout, stderr and stdin

CORE_STREAM_IGNORED_FILES = [ "Tests/LibCore/TestLibCoreStream.cpp" ]
CORE_FILE_IGNORED_FILES = [ "Tests/LibCore/TestLibCoreIODevice.cpp" ]
AK_STREAM_IGNORED_FILES = [ "AK", "Tests/AK/*Stream.cpp", "Userland/Libraries/LibCore/FileStream.h" ]
C_FILE_IGNORED_FILES = [ "Userland/Libraries/LibC", "Libraries/LibC", "LibC", "Tests/LibC", "Ports", "*.sh", "*.py", "*.md", "*.yml" ]

VIEW_FILE_URL = "https://github.com/SerenityOS/serenity/blob/master/"


def fetch_new():
    subprocess.run(["git", "-C", SERENITY_DIR, "fetch"], check=True)


def determine_commit_and_date_list():
    result = subprocess.run(
        [
            "git",
            "-C",
            SERENITY_DIR,
            "log",
            # generate a list of commits that match our regexes
            # this makes the cache size MUCH smaller (needs to store ~1000 commits instead of a full commit history - 45k).
            # however, the script startup time is slow.
            f"-G{CORE_STREAM_REGEX}|{CORE_FILE_REGEX}|{AK_STREAM_REGEX}|{CORE_FILE_REGEX}|{C_FILE_REGEX}"
            "origin/master",
            "--reverse",
            "--format=%H %ct",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    lines.pop()
    assert lines[-1] != "", result.stdout[-10:]
    print(f"Found {len(lines)} commits.")
    entries = []
    for line in lines:
        parts = line.split(" ")
        assert len(parts) == 2, line
        entries.append((parts[0], int(parts[1])))
    return entries


def load_cache():
    if os.path.exists(FILENAME_CACHE):
        with open(FILENAME_CACHE, "r") as fp:
            cache = json.load(fp)
    else:
        print(f"Couldn't find cache file. Regenerating the whole data instead...")
        cache = {}
    return cache


def save_cache(cache):
    with open(FILENAME_CACHE, "w") as fp:
        json.dump(cache, fp, sort_keys=True, separators=",:", indent=0)


def count_repo_occurrences(regex_search, ignored_files):
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-wE", regex_search, "--" ] + list(map(lambda x: f":!{x}", ignored_files)),
        capture_output=True,
        text=True,
    )
    lines = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    return len(lines) - 1


def count_file_occurrences(regex_search, ignored_files):
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-wcE", regex_search, "--" ] + list(map(lambda x: f":!{x}", ignored_files)),
        capture_output=True,
        text=True,
    )
    lines = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    dictionary = dict(x.split(':') for x in lines[:-1])
    return sorted(dictionary.items(), key=lambda x: int(x[1]), reverse=True)


def lookup_commit(commit, date, cache):
    if commit in cache:
        stream_file, core_file, ak_stream, c_file = cache[commit]
    else:
        time_start = time.time()
        subprocess.run(["git", "-C", SERENITY_DIR, "checkout", "-q", commit], check=True)
        stream_file = count_repo_occurrences(CORE_STREAM_REGEX, CORE_STREAM_IGNORED_FILES)
        core_file = count_repo_occurrences(CORE_FILE_REGEX, CORE_FILE_IGNORED_FILES)
        ak_stream = count_repo_occurrences(AK_STREAM_REGEX, AK_STREAM_IGNORED_FILES)
        c_file = count_repo_occurrences(C_FILE_REGEX, C_FILE_IGNORED_FILES)
        time_done_counting = time.time()
        cache[commit] = stream_file, core_file, ak_stream, c_file
        if len(cache) % SAVE_CACHE_INV_FREQ == 0:
            print("    (actually saving cache)")
            save_cache(cache)
        time_done_saving = time.time()
        print(
            f"Extended cache by {commit} (now containing {len(cache)} keys) (counting took {time_done_counting - time_start}s, saving took {time_done_saving - time_done_counting}s)"
        )
    human_readable_time = datetime.datetime.fromtimestamp(date).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return dict(
        commit=commit,
        unix_timestamp=date,
        human_readable_time=human_readable_time,
        stream_file=stream_file,
        core_file=core_file,
        ak_stream=ak_stream,
        c_file=c_file,
    )


def write_graphs(most_recent_commit):
    time_now = int(time.time())
    print(f"Plotting with {time_now=}")
    time_yesteryesterday = time_now - 3600 * 24 * 2
    time_last_week = time_now - 3600 * 24 * 7
    time_last_month = time_now - 3600 * 24 * 31  # All months are 31 days. Right.
    time_last_year = time_now - 3600 * 24 * 366  # All years are 366 days. Right.
    timed_plot_commands = ""

    # *Some* versions of gnuplot use year 2000 as epoch, and in those versions *only*
    # the xrange is interpreted relative to this. Aaargh!
    output = subprocess.check_output(['gnuplot', '--version']).split()
    assert output[0] == b"gnuplot"
    if int(output[1].split(b".")[0]) < 5:
        GNUPLOT_STUPIDITY = 946684800
    else:
        GNUPLOT_STUPIDITY = 0

    print_lines = """ \
        "tagged_history.csv" \
           using 1:2 lw 2 title "Core::Stream", \
        '' using 1:3 lw 1 title "Core::File", \
        '' using 1:4 lw 1 title "AK::Stream", \
        '' using 1:5 lw 1 title "C FILE*", \
        '< tail -n 1 tagged_history.csv' using 1:2:2 with labels point pointtype 7 offset 1,char -.75 notitle, \
        '< tail -n 1 tagged_history.csv' using 1:3:3 with labels point pointtype 7 offset 1,char 0.5 notitle, \
        '< tail -n 1 tagged_history.csv' using 1:4:4 with labels point pointtype 7 offset 1,char 0.5 notitle
    """

    # that's a pretty awful delta cuz it still works per commit rather than per day/whatever but eeeeeehhhhhhh it's good enough for me
    print_delta = """ \
        "tagged_history.csv" \
           using 1:(delta_v($2)) with boxes title "Core::Stream", \
        '' using 1:(delta_v($3)) with boxes title "Core::File", \
        '' using 1:(delta_v($4)) with boxes title "AK::Stream"
    """

    if most_recent_commit > time_last_week:
        timed_plot_commands += f"""
            set boxwidth 3600;
            set output "output_week.png"; plot [{time_last_week - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_lines};
            set output "output_week_delta.png"; plot [{time_last_week - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_delta};
        """
    else:
        print(f"WARNING: No commits in the last week?! (now={time_now}, a week ago={time_last_week}, latest_commit={most_recent_commit})")
    if most_recent_commit > time_last_month:
        timed_plot_commands += f"""
            set boxwidth 3600*6;
            set output "output_month.png"; plot [{time_last_month - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_lines};
            set output "output_month_delta.png"; plot [{time_last_month - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_delta};
        """
    else:
        print(f"ERROR: No commits in the last month?! (now={time_now}, a month ago={time_last_month}, latest_commit={most_recent_commit})")
        raise AssertionError()
    if most_recent_commit > time_last_year:
        timed_plot_commands += f"""
            set boxwidth 3600*24;
            set output "output_year.png"; plot [{time_last_year - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_lines};
            set output "output_year_delta.png"; plot [{time_last_year - GNUPLOT_STUPIDITY}:{time_now - GNUPLOT_STUPIDITY}] {print_delta};
        """
    else:
        print(f"ERROR: No commits in the last YEAR?! (now={time_now}, a year ago={time_last_year}, latest_commit={most_recent_commit})")
        raise AssertionError()

    subprocess.run(
        [
            "gnuplot",
            "-e",
                # delta func stolen from https://stackoverflow.com/a/11902907
                # yes im *that* lazy
            f"""
                delta_v(x) = ( vD = x - old_v, old_v = x, vD);
                old_v = NaN;
                set style fill solid;
                set xzeroaxis;

                set style data steps;
                set terminal pngcairo size 1800,600 enhanced;
                set xdata time;
                set grid xtics;
                set timefmt "%s";
                set format x "%Y-%m-%d";
                set ylabel "Count";
                set datafile separator ",";
                set output "output_total.png";
                set key center top;
                plot {print_lines};

                set terminal pngcairo size 900,300 enhanced;
                {timed_plot_commands}
            """,
        ],
        check=True,
    )


def build_table(name, data):
    text = "<div>"
    text += f"<h3 class=center>{name}</h3>"
    text += "<table><tr><th>File<th>Count"
    for file, count in data:
        text += f"<tr><td class=file><a href='{VIEW_FILE_URL}/{file}'>{file}</a><td>{count}\n"
    text += "</table></div>"
    return text


def write_file_list():
    with open("index.template.html", "r") as fp:
        template = fp.read()

    text = "<div class=streams>"
    text += build_table("Core::File", count_file_occurrences(CORE_FILE_REGEX, CORE_FILE_IGNORED_FILES))
    text += build_table("AK::Stream", count_file_occurrences(AK_STREAM_REGEX, AK_STREAM_IGNORED_FILES))
    text += build_table("C FILE*", count_file_occurrences(C_FILE_REGEX, C_FILE_IGNORED_FILES))
    text += "</div>"

    with open("index.html", "w") as fp:
        fp.write(template.replace('<!-- REPLACE ME -->', text))


def run():
    if not os.path.exists(SERENITY_DIR + "README.md"):
        print(
            f"Can't find Serenity checkout at {SERENITY_DIR} , please make sure that a reasonably recent git checkout is at that location."
        )
        exit(1)
    fetch_new()
    print("Finding commits that added/removed file and stream usage. this might take a while...")
    commits_and_dates = determine_commit_and_date_list()
    print(f"Newest commits are: ...{commits_and_dates[-3 :]}")
    current_time = int(time.time())
    print(
        f"(The time is {current_time}, the last commit is {current_time - commits_and_dates[-1][1]}s ago)"
    )
    cache = load_cache()
    tagged_commits = [
        lookup_commit(commit, date, cache) for commit, date in commits_and_dates
    ]
    save_cache(cache)
    with open(FILENAME_JSON, "w") as fp:
        json.dump(tagged_commits, fp, sort_keys=True, indent=1)
    with open(FILENAME_CSV, "w") as fp:
        for entry in tagged_commits:
            fp.write(f"{entry['unix_timestamp']},{entry['stream_file']},{entry['core_file']},{entry['ak_stream']},{entry['c_file']}\n")
    write_graphs(commits_and_dates[-1][1])
    write_file_list()

if __name__ == "__main__":
    run()
