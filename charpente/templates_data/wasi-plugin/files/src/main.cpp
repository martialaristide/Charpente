// A WASI program: standard input to standard output, no operating system needed. Counts words.
#include <cctype>
#include <cstdio>

int main() {
    long words = 0, chars = 0;
    bool in_word = false;
    for (int c; (c = std::getchar()) != EOF; ++chars) {
        if (std::isspace(c)) in_word = false;
        else if (!in_word) { in_word = true; ++words; }
    }
    std::printf("%ld words, %ld characters\n", words, chars);
    return 0;
}
