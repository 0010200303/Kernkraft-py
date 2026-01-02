union Value:
    int: i32
    string: str

value: Value

value.int = 2807
printf("%d\n", value.int)

value.string = "Tust!"
printf(value.string)
