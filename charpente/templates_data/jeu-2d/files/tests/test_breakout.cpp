#include <cstdio>

#include "breakout.hpp"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAILED: %s (line %d)\n", #cond, __LINE__); ++failures; } } while (0)

int main() {
    using namespace @IDENT@;
    Game game = new_game();
    CHECK(game.bricks.size() == 32 && game.lives == 3 && !game.won() && !game.lost());

    // The paddle stays inside the field.
    for (int i = 0; i < 100; ++i) step(game, 0.05f, +1);
    CHECK(game.paddle.x <= 1.0f - game.paddle.w / 2 + 1e-4f);

    // A ball that misses costs a life.
    Game miss = new_game();
    miss.paddle.x = 0.1f;
    miss.ball_x = 0.9f;
    miss.ball_y = 0.02f;
    miss.ball_dx = 0.0f;
    miss.ball_dy = -0.5f;
    for (int i = 0; i < 20 && miss.lives == 3; ++i) step(miss, 0.05f, 0);
    CHECK(miss.lives == 2);

    // Hitting a brick removes it and scores.
    Game hit = new_game();
    const Rect brick = hit.bricks.front();
    hit.ball_x = brick.x;
    hit.ball_y = brick.y - 0.03f;
    hit.ball_dx = 0.0f;
    hit.ball_dy = 0.5f;
    for (int i = 0; i < 5 && hit.score == 0; ++i) step(hit, 0.05f, 0);
    CHECK(hit.score == 10 && hit.bricks.size() == 31);
    return failures == 0 ? 0 : 1;
}
