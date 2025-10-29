func tust(i: i32) -> void:
    if i == 3:
        printf("3\n")
    elif i == 2:
        printf("2\n")
    elif i == 1:
        printf("1\n")
    elif i == 0:
        printf("0\n")
    else:
        printf("OTHER\n")

x: i32 = 4
tust(x)
x = x - 1
tust(x)
x = x - 1
tust(x)
x = x - 1
tust(x)
x = x - 1
tust(x)

x = x - 1
tust(x)
printf("%d", x)
