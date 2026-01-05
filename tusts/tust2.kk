struct Player:
    name: str
    score: i32

func print_player(player: Player):
    printf("Player %s got %d points!\n", str_to_cstr(player.name), player.score)

player: Player
player.name = "Tust"
player.score = 13

print_player(player)
