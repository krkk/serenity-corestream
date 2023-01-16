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
FILENAME_CACHE_COLD = "cache_cold.json"
# Save the cache only every X commits, instead of after every commit.
SAVE_CACHE_INV_FREQ = 50


core_stream_regex = "Core::Stream"
core_file_regex = "(CFile|Core::File)([&>]|::(open|construct))" # technically there's also try_create() from C_OBJECT macro but thanks god nobody used it
ak_stream_regex = "(Input|Output|(Circular)Duplex|Constrained|Reconsumable)(Bit|File|Memory|)Stream"

core_stream_ignored_files = [ "Tests/LibCore/TestLibCoreStream.cpp" ]
core_file_ignored_files = [ "Tests/LibCore/TestLibCoreIODevice.cpp" ]
ak_stream_ignored_files = [ "AK", "Tests/AK/*Stream.cpp", "Userland/Libraries/LibCore/FileStream.h" ]


def fetch_new():
    subprocess.run(["git", "-C", SERENITY_DIR, "fetch"], check=True)


def determine_commit_and_date_list():
    result = subprocess.run(
        [
            "git",
            "-C",
            SERENITY_DIR,
            "log",
            # list through commits that actually matched that regex.
            # this makes the cache size MUCH smaller (needs to store ~750 commits instead of a full history - 45k).
            # however, the script startup time is now much longer.
            f"-G{core_stream_regex}|{core_file_regex}|{ak_stream_regex}"
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
    if not os.path.exists(FILENAME_CACHE):
        with open(FILENAME_CACHE_COLD, "r") as fp:
            cache = json.load(fp)
        # Make sure it's writable:
        save_cache(cache)
    else:
        with open(FILENAME_CACHE, "r") as fp:
            cache = json.load(fp)
    return cache


def save_cache(cache):
    with open(FILENAME_CACHE, "w") as fp:
        json.dump(cache, fp, sort_keys=True, separators=",:", indent=0)


def count_commit_occurences(regex_search, ignored_files):
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-wE", regex_search, "--" ] + list(map(lambda x: f":!{x}", ignored_files)),
        capture_output=True,
        text=True,
    )
    lines = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    return len(lines) - 1


def lookup_commit(commit, date, cache):
    if commit in cache:
        stream_file, core_file, ak_stream = cache[commit]
    else:
        time_start = time.time()
        subprocess.run(["git", "-C", SERENITY_DIR, "checkout", "-q", commit], check=True)
        stream_file = count_commit_occurences(core_stream_regex, core_stream_ignored_files)
        core_file = count_commit_occurences(core_file_regex, core_file_ignored_files)
        ak_stream = count_commit_occurences(ak_stream_regex, ak_stream_ignored_files)
        time_done_counting = time.time()
        cache[commit] = stream_file, core_file, ak_stream
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

                set style data lines;
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
            if entry is None:
                continue
            fp.write(f"{entry['unix_timestamp']},{entry['stream_file']},{entry['core_file']},{entry['ak_stream']}\n")
    write_graphs(commits_and_dates[-1][1])

if __name__ == "__main__":
    run()
