; ModuleID = "tust_module"
target triple = "x86_64-pc-windows-msvc"
target datalayout = ""

%"Player" = type {i8*, i32}
declare external i32 @"printf"(i8* %".1", ...)

define i32 @"main"(i32 %".1")
{
entry:
  %"x" = alloca i32
  %"player_arr" = alloca [2 x %"Player"]
  ; Expressions originating at 0:0
  %".ptr:player_arr.0.name" = getelementptr [2 x %"Player"], [2 x %"Player"]* %"player_arr", i32 0, i32 0, i32 0
  %".ptr.literal:tust0" = getelementptr [6 x i8], [6 x i8]* @".literal:tust0", i32 0, i32 0
  store i8* %".ptr.literal:tust0", i8** %".ptr:player_arr.0.name"
  %".ptr:player_arr.0.score" = getelementptr [2 x %"Player"], [2 x %"Player"]* %"player_arr", i32 0, i32 0, i32 1
  store i32 1337, i32* %".ptr:player_arr.0.score"
  %".ptr:player_arr.1.name" = getelementptr [2 x %"Player"], [2 x %"Player"]* %"player_arr", i32 0, i32 1, i32 0
  %".ptr.literal:tust1" = getelementptr [6 x i8], [6 x i8]* @".literal:tust1", i32 0, i32 0
  store i8* %".ptr.literal:tust1", i8** %".ptr:player_arr.1.name"
  %".ptr:player_arr.1.score" = getelementptr [2 x %"Player"], [2 x %"Player"]* %"player_arr", i32 0, i32 1, i32 1
  store i32 2807, i32* %".ptr:player_arr.1.score"
  store i32 1, i32* %"x"
  %".load:x" = load i32, i32* %"x"
  %".ptr:player_arr.IdentifierNode(\22x\22, fields=[]) at 29:25
" = getelementptr [2 x %"Player"], [2 x %"Player"]* %"player_arr", i32 0, i32 %".load:x"
  call void @"print_player"(%"Player"* %".ptr:player_arr.IdentifierNode(\22x\22, fields=[]) at 29:25
")
  ret i32 0
}

define void @"print_player"(%"Player"* %"player")
{
entry:
  %".ptr.literal:Player %s:\5cn" = getelementptr [12 x i8], [12 x i8]* @".literal:Player %s:\5cn", i32 0, i32 0
  %".ptr:player.name" = getelementptr %"Player", %"Player"* %"player", i32 0, i32 0
  %".load:player.name" = load i8*, i8** %".ptr:player.name"
  %".call:printf" = call i32 (i8*, ...) @"printf"(i8* %".ptr.literal:Player %s:\5cn", i8* %".load:player.name")
  %".ptr.literal:\5ctscore: %d\5cn" = getelementptr [12 x i8], [12 x i8]* @".literal:\5ctscore: %d\5cn", i32 0, i32 0
  %".ptr:player.score" = getelementptr %"Player", %"Player"* %"player", i32 0, i32 1
  %".load:player.score" = load i32, i32* %".ptr:player.score"
  %".call:printf.1" = call i32 (i8*, ...) @"printf"(i8* %".ptr.literal:\5ctscore: %d\5cn", i32 %".load:player.score")
  ret void
}

@".literal:Player %s:\5cn" = private unnamed_addr constant [12 x i8] c"Player %s:\0a\00"
@".literal:\5ctscore: %d\5cn" = private unnamed_addr constant [12 x i8] c"\09score: %d\0a\00"
@".literal:tust0" = private unnamed_addr constant [6 x i8] c"tust0\00"
@".literal:tust1" = private unnamed_addr constant [6 x i8] c"tust1\00"