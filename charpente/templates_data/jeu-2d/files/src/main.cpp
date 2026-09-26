// Breakout with GLFW and legacy OpenGL. `@NAME@ --frames 120` exits after 120 frames (smoke tests, CI).
#define GL_SILENCE_DEPRECATION
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <GLFW/glfw3.h>
#include "breakout.hpp"

static void fill(const @IDENT@::Rect& r, float red, float green, float blue) {
    glColor3f(red, green, blue);
    glBegin(GL_QUADS);
    glVertex2f(r.x - r.w / 2, r.y - r.h / 2);
    glVertex2f(r.x + r.w / 2, r.y - r.h / 2);
    glVertex2f(r.x + r.w / 2, r.y + r.h / 2);
    glVertex2f(r.x - r.w / 2, r.y + r.h / 2);
    glEnd();
}

int main(int argc, char** argv) {
    long max_frames = 0;
    for (int i = 1; i + 1 < argc; ++i) {
        if (std::strcmp(argv[i], "--frames") == 0) max_frames = std::atol(argv[i + 1]);
    }
    if (!glfwInit()) { std::fprintf(stderr, "glfwInit failed\n"); return 1; }
    GLFWwindow* window = glfwCreateWindow(640, 640, "@TITLE@", nullptr, nullptr);
    if (!window) { std::fprintf(stderr, "could not create a window (is there a display?)\n"); glfwTerminate(); return 2; }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    @IDENT@::Game game = @IDENT@::new_game();
    double last = glfwGetTime();
    long frame = 0;
    while (!glfwWindowShouldClose(window) && (max_frames == 0 || frame < max_frames)) {
        glfwPollEvents();
        const double now = glfwGetTime();
        const float dt = static_cast<float>(now - last);
        last = now;
        int move = 0;
        if (glfwGetKey(window, GLFW_KEY_LEFT) == GLFW_PRESS || glfwGetKey(window, GLFW_KEY_A) == GLFW_PRESS) move -= 1;
        if (glfwGetKey(window, GLFW_KEY_RIGHT) == GLFW_PRESS || glfwGetKey(window, GLFW_KEY_D) == GLFW_PRESS) move += 1;
        @IDENT@::step(game, dt > 0.05f ? 0.05f : dt, move);

        int w, h;
        glfwGetFramebufferSize(window, &w, &h);
        glViewport(0, 0, w, h);
        glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glMatrixMode(GL_PROJECTION);
        glLoadIdentity();
        glOrtho(0, 1, 0, 1, -1, 1);
        glMatrixMode(GL_MODELVIEW);
        glLoadIdentity();
        for (const auto& brick : game.bricks) fill(brick, 0.9f, 0.5f, 0.2f);
        fill(game.paddle, 0.8f, 0.8f, 0.9f);
        fill({game.ball_x, game.ball_y, game.ball_r * 2, game.ball_r * 2}, 1.0f, 1.0f, 1.0f);
        glfwSwapBuffers(window);
        ++frame;
    }
    std::printf("score %d, lives %d, %ld frames\n", game.score, game.lives, frame);
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
