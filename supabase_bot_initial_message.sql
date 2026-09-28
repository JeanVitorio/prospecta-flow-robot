begin;

alter table public.prospecta_bot_configs
    add column if not exists initial_message text not null
        default 'Olá, tudo bem com você?';

alter table public.leads
    add column if not exists first_contact_message text not null
        default 'Olá, tudo bem com você?';

update public.prospecta_bot_configs
set initial_message = 'Olá, tudo bem com você?'
where btrim(coalesce(initial_message, '')) = '';

update public.leads
set first_contact_message = 'Olá, tudo bem com você?'
where btrim(coalesce(first_contact_message, '')) = '';

alter table public.prospecta_bot_configs
    alter column initial_message set default 'Olá, tudo bem com você?',
    alter column initial_message set not null;

alter table public.leads
    alter column first_contact_message set default 'Olá, tudo bem com você?',
    alter column first_contact_message set not null;

do $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'prospecta_bot_configs_initial_message_not_blank'
          and conrelid = 'public.prospecta_bot_configs'::regclass
    ) then
        alter table public.prospecta_bot_configs
            add constraint prospecta_bot_configs_initial_message_not_blank
            check (btrim(initial_message) <> '');
    end if;

    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'leads_first_contact_message_not_blank'
          and conrelid = 'public.leads'::regclass
    ) then
        alter table public.leads
            add constraint leads_first_contact_message_not_blank
            check (btrim(first_contact_message) <> '');
    end if;
end;
$$;

notify pgrst, 'reload schema';

commit;
