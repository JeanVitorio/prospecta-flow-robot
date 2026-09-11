begin;

create extension if not exists pgcrypto;

create table if not exists public.prospecta_bot_configs (
    id uuid primary key default gen_random_uuid(),
    slug text not null,
    name text not null,
    lead_owner_id uuid,
    owner_email text not null,
    search_term text not null,
    niche text not null,
    cities text[] not null default '{}',
    min_reviews integer not null default 0,
    min_reviews_enabled boolean not null default true,
    estimated_ticket numeric(14, 2) not null,
    headless boolean not null default true,
    website_filter text not null default 'without',
    phone_filter text not null default 'any',
    max_scrolls integer not null default 10,
    excluded_words text[] not null default '{}',
    excluded_words_enabled boolean not null default true,
    included_words text[] not null default '{}',
    included_words_enabled boolean not null default true,
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint prospecta_bot_configs_slug_format check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    constraint prospecta_bot_configs_name_not_blank check (btrim(name) <> ''),
    constraint prospecta_bot_configs_email_not_blank check (btrim(owner_email) <> ''),
    constraint prospecta_bot_configs_search_not_blank check (btrim(search_term) <> ''),
    constraint prospecta_bot_configs_niche_not_blank check (btrim(niche) <> ''),
    constraint prospecta_bot_configs_min_reviews_valid check (min_reviews >= 0),
    constraint prospecta_bot_configs_website_filter_valid check (
        website_filter in ('any', 'with', 'without')
    ),
    constraint prospecta_bot_configs_phone_filter_valid check (
        phone_filter in ('any', 'with', 'without')
    ),
    constraint prospecta_bot_configs_ticket_valid check (estimated_ticket >= 0),
    constraint prospecta_bot_configs_max_scrolls_valid check (max_scrolls > 0),
    constraint prospecta_bot_configs_version_valid check (version > 0),
    constraint prospecta_bot_configs_dates_valid check (deleted_at is null or deleted_at >= created_at)
);

alter table public.prospecta_bot_configs
    add column if not exists min_reviews_enabled boolean not null default true,
    add column if not exists website_filter text not null default 'without',
    add column if not exists phone_filter text not null default 'any',
    add column if not exists excluded_words_enabled boolean not null default true,
    add column if not exists included_words_enabled boolean not null default true;

do $$
begin
    if not exists (
        select 1 from pg_catalog.pg_constraint
        where conname = 'prospecta_bot_configs_website_filter_valid'
          and conrelid = 'public.prospecta_bot_configs'::regclass
    ) then
        alter table public.prospecta_bot_configs
            add constraint prospecta_bot_configs_website_filter_valid
            check (website_filter in ('any', 'with', 'without'));
    end if;
    if not exists (
        select 1 from pg_catalog.pg_constraint
        where conname = 'prospecta_bot_configs_phone_filter_valid'
          and conrelid = 'public.prospecta_bot_configs'::regclass
    ) then
        alter table public.prospecta_bot_configs
            add constraint prospecta_bot_configs_phone_filter_valid
            check (phone_filter in ('any', 'with', 'without'));
    end if;
end;
$$;

create unique index if not exists prospecta_bot_configs_slug_active_uidx
    on public.prospecta_bot_configs (slug)
    where deleted_at is null;
create index if not exists prospecta_bot_configs_active_updated_idx
    on public.prospecta_bot_configs (updated_at desc)
    where deleted_at is null;
create index if not exists prospecta_bot_configs_owner_idx
    on public.prospecta_bot_configs (lead_owner_id)
    where deleted_at is null;

create table if not exists public.prospecta_bot_checkpoints (
    bot_id uuid not null references public.prospecta_bot_configs(id) on delete cascade,
    process_name text not null,
    state jsonb not null default '{}'::jsonb,
    status text not null default 'idle',
    runner_id text,
    lease_expires_at timestamptz,
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (bot_id, process_name),
    constraint prospecta_bot_checkpoints_process_not_blank check (btrim(process_name) <> ''),
    constraint prospecta_bot_checkpoints_status_not_blank check (btrim(status) <> ''),
    constraint prospecta_bot_checkpoints_state_object check (jsonb_typeof(state) = 'object'),
    constraint prospecta_bot_checkpoints_version_valid check (version > 0),
    constraint prospecta_bot_checkpoints_lease_pair check (
        (runner_id is null and lease_expires_at is null)
        or (runner_id is not null and lease_expires_at is not null)
    )
);

create index if not exists prospecta_bot_checkpoints_lease_idx
    on public.prospecta_bot_checkpoints (lease_expires_at)
    where lease_expires_at is not null;
create index if not exists prospecta_bot_checkpoints_status_idx
    on public.prospecta_bot_checkpoints (status, updated_at desc);

create table if not exists public.prospecta_bot_runners (
    id text primary key,
    name text not null,
    environment text not null,
    status text not null default 'online',
    metadata jsonb not null default '{}'::jsonb,
    heartbeat_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prospecta_bot_runners_id_not_blank check (btrim(id) <> ''),
    constraint prospecta_bot_runners_name_not_blank check (btrim(name) <> ''),
    constraint prospecta_bot_runners_environment_not_blank check (btrim(environment) <> ''),
    constraint prospecta_bot_runners_metadata_object check (jsonb_typeof(metadata) = 'object')
);

create index if not exists prospecta_bot_runners_heartbeat_idx
    on public.prospecta_bot_runners (heartbeat_at desc);

create table if not exists public.prospecta_bot_controls (
    bot_id uuid primary key references public.prospecta_bot_configs(id) on delete cascade,
    command text not null,
    target_runner_id text,
    request_id uuid not null default gen_random_uuid(),
    requested_at timestamptz not null default now(),
    acknowledged_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prospecta_bot_controls_command_not_blank check (btrim(command) <> '')
);

alter table public.prospecta_bot_controls
    add column if not exists target_runner_id text,
    add column if not exists request_id uuid not null default gen_random_uuid(),
    add column if not exists requested_at timestamptz not null default now(),
    add column if not exists acknowledged_at timestamptz;

create index if not exists prospecta_bot_controls_command_idx
    on public.prospecta_bot_controls (command, updated_at desc);
create index if not exists prospecta_bot_controls_runner_idx
    on public.prospecta_bot_controls (target_runner_id, command, requested_at desc);

create table if not exists public.prospecta_bot_events (
    id bigint generated always as identity primary key,
    event_id uuid not null default gen_random_uuid(),
    bot_id uuid not null references public.prospecta_bot_configs(id) on delete cascade,
    process_name text not null,
    runner_id text,
    event_type text not null,
    level text not null default 'info',
    message text not null,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint prospecta_bot_events_process_not_blank check (btrim(process_name) <> ''),
    constraint prospecta_bot_events_type_not_blank check (btrim(event_type) <> ''),
    constraint prospecta_bot_events_message_not_blank check (btrim(message) <> ''),
    constraint prospecta_bot_events_data_object check (jsonb_typeof(data) = 'object')
);

alter table public.prospecta_bot_events
    add column if not exists event_id uuid not null default gen_random_uuid();

create unique index if not exists prospecta_bot_events_event_id_uidx
    on public.prospecta_bot_events (event_id);
create index if not exists prospecta_bot_events_bot_created_idx
    on public.prospecta_bot_events (bot_id, created_at desc);

create or replace function public.prospecta_touch_versioned_row()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    new.updated_at := clock_timestamp();
    new.version := old.version + 1;
    return new;
end;
$$;

create or replace function public.prospecta_touch_row()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    new.updated_at := clock_timestamp();
    return new;
end;
$$;

create or replace function public.prospecta_log_control_event()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    insert into public.prospecta_bot_events (
        bot_id, process_name, runner_id, event_type, message, data
    )
    values (
        new.bot_id,
        'control',
        new.target_runner_id,
        'comando_solicitado',
        'Comando solicitado: ' || new.command,
        jsonb_build_object(
            'comando', new.command,
            'request_id', new.request_id,
            'target_runner_id', new.target_runner_id
        )
    );
    return new;
end;
$$;

drop trigger if exists prospecta_bot_configs_touch on public.prospecta_bot_configs;
create trigger prospecta_bot_configs_touch
before update on public.prospecta_bot_configs
for each row execute function public.prospecta_touch_versioned_row();

drop trigger if exists prospecta_bot_checkpoints_touch on public.prospecta_bot_checkpoints;
create trigger prospecta_bot_checkpoints_touch
before update on public.prospecta_bot_checkpoints
for each row execute function public.prospecta_touch_versioned_row();

drop trigger if exists prospecta_bot_controls_touch on public.prospecta_bot_controls;
create trigger prospecta_bot_controls_touch
before update on public.prospecta_bot_controls
for each row execute function public.prospecta_touch_row();

drop trigger if exists prospecta_bot_controls_event on public.prospecta_bot_controls;
create trigger prospecta_bot_controls_event
after insert or update of command, request_id on public.prospecta_bot_controls
for each row execute function public.prospecta_log_control_event();

drop trigger if exists prospecta_bot_runners_touch on public.prospecta_bot_runners;
create trigger prospecta_bot_runners_touch
before update on public.prospecta_bot_runners
for each row execute function public.prospecta_touch_row();

alter table public.prospecta_bot_configs enable row level security;
alter table public.prospecta_bot_checkpoints enable row level security;
alter table public.prospecta_bot_controls enable row level security;
alter table public.prospecta_bot_runners enable row level security;
alter table public.prospecta_bot_events enable row level security;

revoke all on table public.prospecta_bot_configs from public, anon, authenticated;
revoke all on table public.prospecta_bot_checkpoints from public, anon, authenticated;
revoke all on table public.prospecta_bot_controls from public, anon, authenticated;
revoke all on table public.prospecta_bot_runners from public, anon, authenticated;
revoke all on table public.prospecta_bot_events from public, anon, authenticated;
grant select, insert, update, delete on table public.prospecta_bot_configs to service_role;
grant select, insert, update, delete on table public.prospecta_bot_checkpoints to service_role;
grant select, insert, update, delete on table public.prospecta_bot_controls to service_role;
grant select, insert, update, delete on table public.prospecta_bot_runners to service_role;
grant select, insert, update on table public.prospecta_bot_events to service_role;
grant usage, select on sequence public.prospecta_bot_events_id_seq to service_role;

create or replace function public.prospecta_claim_checkpoint(
    p_bot_id uuid,
    p_process_name text,
    p_runner_id text,
    p_lease_seconds integer default 300
)
returns setof public.prospecta_bot_checkpoints
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if btrim(coalesce(p_process_name, '')) = '' then
        raise exception 'Nome do processo é obrigatório';
    end if;
    if btrim(coalesce(p_runner_id, '')) = '' then
        raise exception 'Identificador do executor é obrigatório';
    end if;
    if p_lease_seconds < 1 or p_lease_seconds > 86400 then
        raise exception 'Duração do lease deve estar entre 1 e 86400 segundos';
    end if;

    return query
    insert into public.prospecta_bot_checkpoints (
        bot_id, process_name, status, runner_id, lease_expires_at
    )
    values (
        p_bot_id, p_process_name, 'running', p_runner_id,
        clock_timestamp() + make_interval(secs => p_lease_seconds)
    )
    on conflict (bot_id, process_name) do update
    set status = 'running',
        runner_id = excluded.runner_id,
        lease_expires_at = excluded.lease_expires_at
    where prospecta_bot_checkpoints.runner_id = p_runner_id
       or prospecta_bot_checkpoints.lease_expires_at is null
       or prospecta_bot_checkpoints.lease_expires_at < clock_timestamp()
    returning prospecta_bot_checkpoints.*;
end;
$$;

create or replace function public.prospecta_save_checkpoint(
    p_bot_id uuid,
    p_process_name text,
    p_runner_id text,
    p_state jsonb,
    p_status text default 'running',
    p_expected_version bigint default null,
    p_lease_seconds integer default 300
)
returns setof public.prospecta_bot_checkpoints
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if jsonb_typeof(coalesce(p_state, '{}'::jsonb)) <> 'object' then
        raise exception 'Estado do checkpoint deve ser um objeto JSON';
    end if;
    if btrim(coalesce(p_status, '')) = '' then
        raise exception 'Status é obrigatório';
    end if;
    if p_lease_seconds < 1 or p_lease_seconds > 86400 then
        raise exception 'Duração do lease deve estar entre 1 e 86400 segundos';
    end if;

    return query
    update public.prospecta_bot_checkpoints
    set state = coalesce(p_state, '{}'::jsonb),
        status = p_status,
        lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds)
    where bot_id = p_bot_id
      and process_name = p_process_name
      and runner_id = p_runner_id
      and lease_expires_at >= clock_timestamp()
      and (p_expected_version is null or version = p_expected_version)
    returning prospecta_bot_checkpoints.*;
end;
$$;

create or replace function public.prospecta_release_checkpoint(
    p_bot_id uuid,
    p_process_name text,
    p_runner_id text,
    p_status text default 'idle',
    p_expected_version bigint default null
)
returns setof public.prospecta_bot_checkpoints
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if btrim(coalesce(p_status, '')) = '' then
        raise exception 'Status é obrigatório';
    end if;

    return query
    update public.prospecta_bot_checkpoints
    set status = p_status,
        runner_id = null,
        lease_expires_at = null
    where bot_id = p_bot_id
      and process_name = p_process_name
      and runner_id = p_runner_id
      and (p_expected_version is null or version = p_expected_version)
    returning prospecta_bot_checkpoints.*;
end;
$$;

create or replace function public.prospecta_is_admin(p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select exists (
        select 1
        from public.user_roles
        where user_id = p_user_id
          and role::text = 'leader'
    );
$$;

create or replace function public.prospecta_can_access_bot(p_bot_id uuid)
returns boolean
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select auth.uid() is null
        or public.prospecta_is_admin(auth.uid())
        or exists (
            select 1
            from public.prospecta_bot_configs
            where id = p_bot_id
              and lead_owner_id = auth.uid()
              and deleted_at is null
        );
$$;

create or replace function public.prospecta_request_command(
    p_bot_id uuid,
    p_command text,
    p_target_runner_id text default null
)
returns setof public.prospecta_bot_controls
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if btrim(coalesce(p_command, '')) = '' then
        raise exception 'Comando é obrigatório';
    end if;
    if p_command not in ('rodando', 'pausado', 'parado') then
        raise exception 'Comando inválido';
    end if;
    if not public.prospecta_can_access_bot(p_bot_id) then
        raise exception 'Acesso negado ao bot';
    end if;

    return query
    insert into public.prospecta_bot_controls (
        bot_id, command, target_runner_id, request_id, requested_at, acknowledged_at
    )
    values (
        p_bot_id, p_command, nullif(btrim(p_target_runner_id), ''),
        gen_random_uuid(), clock_timestamp(), null
    )
    on conflict (bot_id) do update
    set command = excluded.command,
        target_runner_id = excluded.target_runner_id,
        request_id = excluded.request_id,
        requested_at = excluded.requested_at,
        acknowledged_at = null
    returning prospecta_bot_controls.*;
end;
$$;

create or replace function public.prospecta_get_bot_runtime(p_bot_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select jsonb_build_object(
        'config', to_jsonb(config),
        'control', (
            select to_jsonb(control)
            from public.prospecta_bot_controls control
            where control.bot_id = config.id
        ),
        'runner', (
            select to_jsonb(runner)
            from public.prospecta_bot_runners runner
            join public.prospecta_bot_controls control
              on control.target_runner_id = runner.id
            where control.bot_id = config.id
        ),
        'checkpoints', coalesce((
            select jsonb_object_agg(checkpoint.process_name, to_jsonb(checkpoint))
            from public.prospecta_bot_checkpoints checkpoint
            where checkpoint.bot_id = config.id
        ), '{}'::jsonb)
    )
    from public.prospecta_bot_configs config
    where config.id = p_bot_id
      and config.deleted_at is null
      and public.prospecta_can_access_bot(config.id);
$$;

create or replace function public.prospecta_get_bot_events(
    p_bot_id uuid,
    p_limit integer default 100
)
returns setof public.prospecta_bot_events
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select event.*
    from public.prospecta_bot_events event
    where event.bot_id = p_bot_id
      and public.prospecta_can_access_bot(event.bot_id)
    order by event.created_at desc
    limit least(greatest(coalesce(p_limit, 100), 1), 500);
$$;

create or replace function public.prospecta_list_runners()
returns table (
    id text,
    name text,
    environment text,
    status text,
    heartbeat_at timestamptz
)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select runner.id, runner.name, runner.environment, runner.status,
           runner.heartbeat_at
    from public.prospecta_bot_runners runner
    where runner.status = 'online'
      and runner.heartbeat_at >= clock_timestamp() - interval '90 seconds'
    order by runner.name;
$$;

create or replace function public.prospecta_list_bot_runtimes()
returns table (runtime jsonb)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select public.prospecta_get_bot_runtime(config.id) as runtime
    from public.prospecta_bot_configs config
    where config.deleted_at is null
      and public.prospecta_can_access_bot(config.id)
    order by config.name;
$$;

create or replace function public.prospecta_get_recent_bot_events(
    p_limit integer default 20
)
returns setof public.prospecta_bot_events
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select event.*
    from public.prospecta_bot_events event
    where public.prospecta_can_access_bot(event.bot_id)
    order by event.created_at desc
    limit least(greatest(coalesce(p_limit, 20), 1), 100);
$$;

grant select, insert, update on table public.prospecta_bot_configs to authenticated;
grant select on table public.prospecta_bot_checkpoints to authenticated;
grant select on table public.prospecta_bot_controls to authenticated;
grant select on table public.prospecta_bot_events to authenticated;

drop policy if exists prospecta_configs_select_scope on public.prospecta_bot_configs;
create policy prospecta_configs_select_scope
on public.prospecta_bot_configs for select to authenticated
using (
    deleted_at is null
    and (
        lead_owner_id = auth.uid()
        or public.prospecta_is_admin(auth.uid())
    )
);

drop policy if exists prospecta_configs_insert_scope on public.prospecta_bot_configs;
create policy prospecta_configs_insert_scope
on public.prospecta_bot_configs for insert to authenticated
with check (
    lead_owner_id = auth.uid()
    or public.prospecta_is_admin(auth.uid())
);

drop policy if exists prospecta_configs_update_scope on public.prospecta_bot_configs;
create policy prospecta_configs_update_scope
on public.prospecta_bot_configs for update to authenticated
using (
    lead_owner_id = auth.uid()
    or public.prospecta_is_admin(auth.uid())
)
with check (
    lead_owner_id = auth.uid()
    or public.prospecta_is_admin(auth.uid())
);

drop policy if exists prospecta_checkpoints_select_scope on public.prospecta_bot_checkpoints;
create policy prospecta_checkpoints_select_scope
on public.prospecta_bot_checkpoints for select to authenticated
using (public.prospecta_can_access_bot(bot_id));

drop policy if exists prospecta_controls_select_scope on public.prospecta_bot_controls;
create policy prospecta_controls_select_scope
on public.prospecta_bot_controls for select to authenticated
using (public.prospecta_can_access_bot(bot_id));

drop policy if exists prospecta_events_select_scope on public.prospecta_bot_events;
create policy prospecta_events_select_scope
on public.prospecta_bot_events for select to authenticated
using (public.prospecta_can_access_bot(bot_id));

revoke all on function public.prospecta_claim_checkpoint(uuid, text, text, integer)
    from public, anon, authenticated;
revoke all on function public.prospecta_save_checkpoint(uuid, text, text, jsonb, text, bigint, integer)
    from public, anon, authenticated;
revoke all on function public.prospecta_release_checkpoint(uuid, text, text, text, bigint)
    from public, anon, authenticated;
revoke all on function public.prospecta_request_command(uuid, text, text)
    from public, anon, authenticated;
revoke all on function public.prospecta_get_bot_runtime(uuid)
    from public, anon, authenticated;
revoke all on function public.prospecta_get_bot_events(uuid, integer)
    from public, anon, authenticated;
revoke all on function public.prospecta_is_admin(uuid)
    from public, anon, authenticated;
revoke all on function public.prospecta_can_access_bot(uuid)
    from public, anon, authenticated;
revoke all on function public.prospecta_list_runners()
    from public, anon, authenticated;
revoke all on function public.prospecta_list_bot_runtimes()
    from public, anon, authenticated;
revoke all on function public.prospecta_get_recent_bot_events(integer)
    from public, anon, authenticated;
grant execute on function public.prospecta_claim_checkpoint(uuid, text, text, integer)
    to service_role;
grant execute on function public.prospecta_save_checkpoint(uuid, text, text, jsonb, text, bigint, integer)
    to service_role;
grant execute on function public.prospecta_release_checkpoint(uuid, text, text, text, bigint)
    to service_role;
grant execute on function public.prospecta_request_command(uuid, text, text)
    to service_role;
grant execute on function public.prospecta_get_bot_runtime(uuid)
    to service_role;
grant execute on function public.prospecta_get_bot_events(uuid, integer)
    to service_role;
grant execute on function public.prospecta_is_admin(uuid)
    to service_role, authenticated;
grant execute on function public.prospecta_can_access_bot(uuid)
    to service_role, authenticated;
grant execute on function public.prospecta_request_command(uuid, text, text)
    to authenticated;
grant execute on function public.prospecta_get_bot_runtime(uuid)
    to authenticated;
grant execute on function public.prospecta_get_bot_events(uuid, integer)
    to authenticated;
grant execute on function public.prospecta_list_runners()
    to service_role, authenticated;
grant execute on function public.prospecta_list_bot_runtimes()
    to service_role, authenticated;
grant execute on function public.prospecta_get_recent_bot_events(integer)
    to service_role, authenticated;

revoke all on function public.prospecta_touch_versioned_row() from public, anon, authenticated;
revoke all on function public.prospecta_touch_row() from public, anon, authenticated;
revoke all on function public.prospecta_log_control_event() from public, anon, authenticated;

commit;
