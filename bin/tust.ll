; ModuleID = "tust_module"
target triple = "x86_64-pc-windows-msvc"
target datalayout = ""

declare external i32 @"printf"(i8* %".1", ...)

define i32 @"main"(i32 %".1")
{
entry:
  %"i" = alloca i32
  %"string" = alloca i8*
  ; Expressions originating at 0:0
  %".ptr.literal:Tust!" = getelementptr [6 x i8], [6 x i8]* @".literal:Tust!", i32 0, i32 0
  store i8* %".ptr.literal:Tust!", i8** %"string"
  store i32 0, i32* %"i"
  %".load:i" = load i32, i32* %"i"
  %".lt" = icmp slt i32 %".load:i", 5
  br i1 %".lt", label %"while.loop", label %"while.after"
while.loop:
  %"c" = alloca i8
  ; while body
  %".load:i.1" = load i32, i32* %"i"
  %".ptr:string.i" = getelementptr i8*, i8** %"string", i32 0
  %".load:string.i" = load i8*, i8** %".ptr:string.i"
  %".ptr:string.i.1" = getelementptr i8, i8* %".load:string.i", i32 %".load:i.1"
  %".load:string.i.1" = load i8, i8* %".ptr:string.i.1"
  store i8 %".load:string.i.1", i8* %"c"
  %".ptr.literal:%c\5cn" = getelementptr [4 x i8], [4 x i8]* @".literal:%c\5cn", i32 0, i32 0
  %".load:c" = load i8, i8* %"c"
  %".call:printf" = call i32 (i8*, ...) @"printf"(i8* %".ptr.literal:%c\5cn", i8 %".load:c")
  %".load:i.2" = load i32, i32* %"i"
  %".add" = add i32 %".load:i.2", 1
  store i32 %".add", i32* %"i"
  ; termination test
  %".load:i.3" = load i32, i32* %"i"
  %".lt.1" = icmp slt i32 %".load:i.3", 5
  br i1 %".lt.1", label %"while.loop", label %"while.after"
while.after:
  ret i32 0
}

@".literal:Tust!" = private unnamed_addr constant [6 x i8] c"Tust!\00"
@".literal:%c\5cn" = private unnamed_addr constant [4 x i8] c"%c\0a\00"