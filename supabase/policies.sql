-- 比喩生成システム：global_timeline のアクセス制御（RLS）
-- Supabase ダッシュボードの SQL Editor に貼って Run する。何度実行しても同じ結果になる。
--
-- 方針
--   読む   ：誰でもOK
--   投稿   ：誰でもOK（ただし文字数などの条件つき）
--   変更   ：誰にも許可しない
--   削除   ：直接は誰にも許可しない。投稿時に発行した「合言葉」を知っている人だけが
--            delete_own_post 関数を通して消せる（DBには合言葉のハッシュだけを保存）

-- 1. 削除用の合言葉のハッシュを入れる列
alter table public.global_timeline
  add column if not exists delete_token_hash text;

-- 2. RLS を有効にする（有効にすると、ポリシーで許可したこと以外はすべて拒否される）
alter table public.global_timeline enable row level security;

-- 3. 既存のポリシーを消してから作り直す
do $$
declare p record;
begin
  for p in select policyname from pg_policies
           where schemaname = 'public' and tablename = 'global_timeline'
  loop
    execute format('drop policy %I on public.global_timeline', p.policyname);
  end loop;
end $$;

create policy "anyone can read"
  on public.global_timeline for select
  to anon, authenticated
  using (true);

create policy "anyone can post"
  on public.global_timeline for insert
  to anon, authenticated
  with check (
    char_length(user_input) between 5 and 100
    and char_length(metaphor) between 1 and 200
    and coalesce(char_length(explanation), 0) <= 600
    and delete_token_hash is not null
  );

-- update / delete のポリシーは作らない ＝ 直接の変更・削除はできない

-- 4. 合言葉が合っているときだけ削除する関数
create or replace function public.delete_own_post(p_id bigint, p_token text)
returns boolean
language sql
security definer
set search_path = public
as $$
  with deleted as (
    delete from public.global_timeline
    where id = p_id
      and delete_token_hash is not null
      and delete_token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
    returning 1
  )
  select exists (select 1 from deleted);
$$;

revoke all on function public.delete_own_post(bigint, text) from public;
grant execute on function public.delete_own_post(bigint, text) to anon, authenticated;
