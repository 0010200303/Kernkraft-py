data = "I love you!"

fd = open("tusts/output.txt", 577, 420)
if fd == -1:
    printf("error while opening file: %d", get_errno())
    return 0

write(fd, str_to_cstr(data), 11)

close_err = close(fd)
if close_err < 0:
    printf("error while closing file: %d", get_errno())
    return 0

printf("\nexited successfully")
