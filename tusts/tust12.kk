union Tust:
    i: i32
    s: str

tust: Tust
tust.i = 2807
printf("%d\n", tust is i32)

tust.s = "Tust"
printf("%d\n", tust is i32)



int: i32 = 2807
printf("%d\n", int is i32)
printf("%d\n", int is str)
