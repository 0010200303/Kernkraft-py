struct Player:
    name: str
    score: i32

func print_player(player: Player) -> void:
    printf("Player %s:\n", player.name)
    printf("\tscore: %d\n", player.score)

player_arr: Player[2]

player_arr[0].name = "tust0"
player_arr[0].score = 1337

player_arr[1].name = "tust1"
player_arr[1].score = 2807

//i: i32 = 0
//while i < 2:
//    print_player(player_arr[i])
//
//    i = i + 1

x = 1
printf(player_arr[x].name)
