buffer: i8[128]

fd = open("tusts/input.txt", 0, 0)
if fd == -1:
    printf("error while opening file: %d", get_errno())
    return 0

size = read(fd, buffer, 128)

pos: i32 = 0
while pos < size:
    printf("%c", buffer[pos])
    pos = pos + 1
printf("\n")

close_err = close(fd)
if close_err < 0:
    printf("error while closing file: %d", get_errno())
    return 0

printf("\nexited successfully")
