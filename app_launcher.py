"""Launch process that is not child process of python or AYON launcher.

This is written for linux distributions where process tree may affect what
is when closed or blocked to be closed.
"""
import contextlib

import os
import sys
import json
import shlex
import tempfile
import time


def main(input_json_path):
    """Read launch arguments from json file and launch the process.

    Expected that json contains "args" key with string or list of strings.

    Arguments are converted to string using `list2cmdline`. At the end is added
    `&` which will cause that launched process is detached and running as
    "background" process.

    ## Notes
    @iLLiCiT: This should be possible to do with 'disown' or double forking but
        I didn't find a way how to do it properly. Disown didn't work as
        expected for me and double forking killed parent process which is
        unexpected too.
    """
    with open(input_json_path, "r") as stream:
        data = json.load(stream)

    # Change environment variables
    env = data.get("env") or {}
    for key, value in env.items():
        os.environ[key] = value

    # Prepare launch arguments
    args = data["args"]
    if isinstance(args, list):
        args = shlex.join(args)

    # Run the command as background process and echo the pid to tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        pid_path = tmpfile.name

    stdout_path = stderr_path = "/dev/null"
    if "stdout" in data:
        stdout_path = data["stdout"]

    if "stderr" in data:
        stderr_path = data["stderr"]

    post_args = []
    if stdout_path:
        stdout = f">{stdout_path}"
        post_args.append(stdout)

    if stderr_path:
        if stdout_path == stderr_path:
            stderr_path = "&1"
        stderr = f"2>{stderr_path}"
        post_args.append(stderr)

    post_args_s = ""
    if post_args:
        joined_args = " ".join(post_args)
        post_args_s = f" {joined_args}"

    shell_cmd = f"{args}{post_args_s} & echo $! > {pid_path}"
    os.system(shell_cmd)

    with open(pid_path, "r") as stream:
        content = stream.read()
    os.remove(pid_path)

    try:
        pid = int(content)
    except Exception:
        initial_pid = None

    # Check if shell script provided actual application PID via PID file
    final_pid = initial_pid
    if pid_file_path and final_pid:
        # Wait a short time for shell script to potentially write actual PID
        time.sleep(0.5)  # Give shell script time to launch app and write PID

        with contextlib.suppress(OSError, ValueError):
            with open(pid_file_path, "r") as pid_file:
                script_pid_content = pid_file.read().strip()
                if script_pid_content.isdigit():
                    script_pid = int(script_pid_content)
                    # Only use if different from shell PID
                    if script_pid != final_pid:
                        final_pid = script_pid
    data["pid"] = final_pid
    with open(input_json_path, "w") as stream:
        json.dump(data, stream)
    sys.exit(0)


if __name__ == "__main__":
    # Expect that last argument is path to a json with launch args information
    json_path = sys.argv[-1]
    if os.path.splitext(json_path)[1].lower() != ".json":
        print((
            "App launcher expects json file as last argument."
            "\nNote: 'app_launcher' is not an executable of AYON launcher."
            " Use 'ayon' instead."
        ))
        sys.exit(1)

    main(json_path)
