begin;

alter table public.leads
    add column if not exists google_maps_url text;

update public.leads
set google_maps_url = null
where google_maps_url is not null
  and btrim(google_maps_url) = '';

update public.leads
set google_maps_url = btrim(notes),
    notes = null
where nullif(btrim(google_maps_url), '') is null
  and btrim(coalesce(notes, '')) ~*
      '^https?://(([^/]+\.)?google\.(com|com\.br)/maps|maps\.app\.goo\.gl/|goo\.gl/maps)';

do $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'leads_google_maps_url_not_blank'
          and conrelid = 'public.leads'::regclass
    ) then
        alter table public.leads
            add constraint leads_google_maps_url_not_blank
            check (google_maps_url is null or btrim(google_maps_url) <> '');
    end if;
end;
$$;

notify pgrst, 'reload schema';

commit;
