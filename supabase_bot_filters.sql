begin;

-- Preserva o comportamento dos bots existentes:
-- sem site, avaliações ativas e filtros de palavras ativos.
alter table public.prospecta_bot_configs
    add column if not exists min_reviews_enabled boolean not null default true,
    add column if not exists website_filter text not null default 'without',
    add column if not exists phone_filter text not null default 'any',
    add column if not exists excluded_words_enabled boolean not null default true,
    add column if not exists included_words_enabled boolean not null default true;

do $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'prospecta_bot_configs_website_filter_valid'
          and conrelid = 'public.prospecta_bot_configs'::regclass
    ) then
        alter table public.prospecta_bot_configs
            add constraint prospecta_bot_configs_website_filter_valid
            check (website_filter in ('any', 'with', 'without'));
    end if;

    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'prospecta_bot_configs_phone_filter_valid'
          and conrelid = 'public.prospecta_bot_configs'::regclass
    ) then
        alter table public.prospecta_bot_configs
            add constraint prospecta_bot_configs_phone_filter_valid
            check (phone_filter in ('any', 'with', 'without'));
    end if;
end;
$$;

notify pgrst, 'reload schema';

commit;
