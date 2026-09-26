#pragma once
#include <vector>

namespace @IDENT@ {

struct Rect { float x, y, w, h; };            // x, y = centre; the play field is 0..1 in both directions

struct Game {
    Rect paddle{0.5f, 0.05f, 0.2f, 0.03f};
    float ball_x = 0.5f, ball_y = 0.2f, ball_dx = 0.35f, ball_dy = 0.5f, ball_r = 0.015f;
    std::vector<Rect> bricks;
    int score = 0;
    int lives = 3;
    bool won() const { return bricks.empty(); }
    bool lost() const { return lives <= 0; }
};

Game new_game();
// Advances the game by `dt` seconds; `move` is -1 (left), 0 or +1 (right).
void step(Game& game, float dt, int move);

}  // namespace @IDENT@
