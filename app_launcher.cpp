/**
This is a simple C++ equivalent of the `app_launcher.py` with one difference:
it completely detach from the parent process. This is needed to avoid
hanging child processes when the parent process is killed.
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

    auto env = root.find("env");
    char **new_environ = NULL;
    if (env != root.end() && env->is_object()) {
        int env_size = env->size();
        new_environ = (char **)malloc((env_size + 1) * sizeof(char *));
        int i = 0;

        for (auto& [key, value] : env->items()) {
            if (value.is_string()) {
                std::string env_var = key + "=" + value.get<std::string>();
                new_environ[i] = strdup(env_var.c_str());
                i++;
            }
        }
        new_environ[env_size] = NULL;
    }
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

        // Redirect stdout to /dev/null
        posix_spawn_file_actions_addopen(&file_actions, STDOUT_FILENO, "/dev/null", O_WRONLY | O_CREAT | O_TRUNC, 0644);

        // Redirect stderr to /dev/null
        posix_spawn_file_actions_addopen(&file_actions, STDERR_FILENO, "/dev/null", O_WRONLY | O_CREAT | O_TRUNC, 0644);

        posix_spawnattr_t spawnattr;
        posix_spawnattr_init(&spawnattr);

        pid_t pid;
        int status = posix_spawn(&pid, exec_args[0], &file_actions, &spawnattr, exec_args, new_environ);

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
