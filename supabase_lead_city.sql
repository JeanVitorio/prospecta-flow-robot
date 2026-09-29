begin;

alter table public.leads
    add column if not exists city text;

update public.leads
set city = null
where city is not null
  and btrim(city) = '';

do $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'leads_city_not_blank'
          and conrelid = 'public.leads'::regclass
    ) then
        alter table public.leads
            add constraint leads_city_not_blank
            check (city is null or btrim(city) <> '');
    end if;
end;
$$;

notify pgrst, 'reload schema';

commit;
