/**
LINUX only

This is a simple C++ application to start process and completely detach it
from the parent process. This is needed to avoid hanging child processes
when the parent process is killed.

You can use it instead of the `app_launcher.py` by building it with:
```shell
CPLUS_INCLUDE_PATH=/../ayon-launcher/vendor/include
g++ app_launcher.cpp -o app_launcher
```
**/
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <spawn.h>
#include <sys/wait.h>
#include <string.h>
#include <fstream>
#include <thread>
#include <chrono>
#include <nlohmann/json.hpp>
using json = nlohmann::json;


int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <json_file>\n", argv[0]);
        return 1;
    }

    std::ifstream json_file(argv[1]);
    if (!json_file.is_open()) {
        fprintf(stderr, "error: could not open file %s\n", argv[1]);
        return 1;
    }

    json root;
    try {
        json_file >> root;
    } catch (json::parse_error& e) {
        fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
    json_file.close();

    auto env = root.find("env");
    char **new_environ = NULL;
    if (env != root.end() && env->is_object()) {
        int env_size = env->size();

        // Check if we need to add AYON_PID_FILE to environment
        auto pid_file_it = root.find("pid_file");
        bool has_pid_file = (pid_file_it != root.end() && pid_file_it->is_string());
        if (has_pid_file && env->find("AYON_PID_FILE") == env->end()) {
            env_size++; // Add space for AYON_PID_FILE
        }

        new_environ = (char **)malloc((env_size + 1) * sizeof(char *));
        int i = 0;

        for (auto& [key, value] : env->items()) {
            if (value.is_string()) {
                std::string env_var = key + "=" + value.get<std::string>();
                new_environ[i] = strdup(env_var.c_str());
                i++;
            }
        }

        // Add AYON_PID_FILE environment variable if pid_file is specified
        if (has_pid_file && env->find("AYON_PID_FILE") == env->end()) {
            std::string pid_file_env = "AYON_PID_FILE=" + pid_file_it->get<std::string>();
            new_environ[i] = strdup(pid_file_env.c_str());
            i++;
        }

        new_environ[env_size] = NULL;
    } else {
        // No env object, but check if we need to create one for pid_file
        auto pid_file_it = root.find("pid_file");
        if (pid_file_it != root.end() && pid_file_it->is_string()) {
            new_environ = (char **)malloc(2 * sizeof(char *));
            std::string pid_file_env = "AYON_PID_FILE=" + pid_file_it->get<std::string>();
            new_environ[0] = strdup(pid_file_env.c_str());
            new_environ[1] = NULL;
        }
    }
    auto stdoutIt = root.find("stdout");
    std::string outPathStr;
    bool addStdoutRedirection = true;
    if (stdoutIt != root.end()) {
        if (stdoutIt->is_null()) {
            addStdoutRedirection = false;  // do not redirect stdout if explicitly null
        } else if (stdoutIt->is_string()) {
            outPathStr = stdoutIt->get<std::string>();
        }
    }
    if (addStdoutRedirection && outPathStr.empty()) outPathStr = "/dev/null";

    auto stderrIt = root.find("stderr");
    std::string errPathStr;
    bool addStderrRedirection = true;
    if (stderrIt != root.end()) {
        if (stderrIt->is_null()) {
            addStderrRedirection = false;  // do not redirect stderr if explicitly null
        } else if (stderrIt->is_string()) {
            errPathStr = stderrIt->get<std::string>();
        }
    }
    if (addStderrRedirection && errPathStr.empty()) errPathStr = "/dev/null";

    auto args = root.find("args");
    if (args != root.end() && args->is_array()) {
        char **exec_args = (char **)malloc((args->size() + 2) * sizeof(char *));
        int index = 0;

        for (const auto& value : *args) {
            if (value.is_string()) {
                exec_args[index] = strdup(value.get<std::string>().c_str());
                index++;
            }
        }
        exec_args[args->size()] = NULL;

        posix_spawn_file_actions_t file_actions;
        posix_spawn_file_actions_init(&file_actions);

        // Redirect stdout only if not explicitly disabled by null
        if (addStdoutRedirection) {
            posix_spawn_file_actions_addopen(&file_actions, STDOUT_FILENO, outPathStr.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
        }

        // Redirect stderr only if not explicitly disabled by null
        if (addStderrRedirection) {
            posix_spawn_file_actions_addopen(&file_actions, STDERR_FILENO, errPathStr.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
        }

        posix_spawnattr_t spawnattr;
        posix_spawnattr_init(&spawnattr);

        pid_t initial_pid;
        int status = posix_spawn(&initial_pid, exec_args[0], &file_actions, &spawnattr, exec_args, new_environ);

        pid_t final_pid = initial_pid;

        if (status == 0) {
            // Check if shell script provided actual application PID via PID file
            auto pid_file_it = root.find("pid_file");
            if (pid_file_it != root.end() && pid_file_it->is_string()) {
                std::string pid_file_path = pid_file_it->get<std::string>();

                // Wait a short time for shell script to potentially write actual PID
                std::this_thread::sleep_for(std::chrono::milliseconds(500));

                std::ifstream pid_file(pid_file_path);
                if (pid_file.is_open()) {
                    std::string pid_content;
                    std::getline(pid_file, pid_content);
                    pid_file.close();

                    // Remove any whitespace
                    pid_content.erase(0, pid_content.find_first_not_of(" \t\r\n"));
                    pid_content.erase(pid_content.find_last_not_of(" \t\r\n") + 1);

                    if (!pid_content.empty()) {
                        try {
                            pid_t script_pid = std::stoi(pid_content);
                            if (script_pid != initial_pid && script_pid > 0) {
                                final_pid = script_pid;
                                printf("Shell script provided actual application PID: %d\n", script_pid);
                            }
                        } catch (const std::exception& e) {
                            // Invalid PID in file, use initial_pid
                        }
                    }
                }
            }

            root["pid"] = final_pid;
        } else {
            root["pid"] = nullptr;
        }

        std::ofstream output_file(argv[1]);
        if (output_file.is_open()) {
            output_file << root.dump();
            output_file.close();
        } else {
            fprintf(stderr, "error: could not write back to file %s\n", argv[1]);
        }

        if (status != 0) {
            printf("posix_spawn: %s\n", strerror(status));
            setsid();
            return 1;
        }

        posix_spawn_file_actions_destroy(&file_actions);

        for (int i = 0; i < env->size(); i++) {
            free(new_environ[i]);
        }
        free(exec_args);
    }
    setsid();

    return 0;
}
