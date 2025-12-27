struct Player:
    name: str
    score: i32

struct Scoreboard:
    player1: Player
    player2: Player

scoreboard: Scoreboard

scoreboard.player1.name = "tust0"
scoreboard.player1.score = 1337

scoreboard.player2.name = "tust1"
scoreboard.player2.score = 2807

printf("Player %s has %d Points!\n", scoreboard.player1.name, scoreboard.player1.score)
printf("Player %s has %d Points!\n", scoreboard.player2.name, scoreboard.player2.score)
