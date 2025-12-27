buffer: i8[128]
buffer[0] = 73   // I
buffer[1] = 32   // ' '
buffer[2] = 108  // l
buffer[3] = 111  // o
buffer[4] = 118  // v
buffer[5] = 101  // e
buffer[6] = 32   // ' '
buffer[7] = 121  // y
buffer[8] = 111  // o
buffer[9] = 117  // u
buffer[10] = 33  // !

fd = open("tusts/output.txt", 577, 420)
if fd == -1:
    printf("error while opening file: %d", get_errno())
    return 0

write(fd, array128_i8_to_ptr(buffer), 11)

close_err = close(fd)
if close_err < 0:
    printf("error while closing file: %d", get_errno())
    return 0

printf("\nexited successfully")
