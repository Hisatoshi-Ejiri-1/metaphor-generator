-- 比喩生成システム：テーブル定義
-- 新しく作るときは、これを実行してから policies.sql を実行する。
-- すでにテーブルがある場合は何も変わらない。

create table if not exists public.global_timeline (
  id                bigserial primary key,
  created_at        timestamptz not null default now(),
  user_input        text not null,
  metaphor          text not null,
  explanation       text,
  delete_token_hash text
);

-- 新しい順に並べて表示するため
create index if not exists global_timeline_created_at_idx
  on public.global_timeline (created_at desc);
