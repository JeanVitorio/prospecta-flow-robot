begin;

create extension if not exists pgcrypto;

alter table public.leads
    add column if not exists whatsapp_do_not_contact boolean not null default false;

create table if not exists public.prospecta_whatsapp_sessions (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    owner_id uuid not null,
    status text not null default 'disconnected',
    runner_id text,
    connected_number text,
    qr_code_data_url text,
    qr_generated_at timestamptz,
    last_error text,
    last_seen_at timestamptz,
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint prospecta_whatsapp_sessions_name_not_blank
        check (btrim(name) <> ''),
    constraint prospecta_whatsapp_sessions_status_valid
        check (status in (
            'disconnected', 'connecting', 'qr_pending', 'ready', 'error'
        ))
);

create index if not exists prospecta_whatsapp_sessions_owner_idx
    on public.prospecta_whatsapp_sessions (owner_id, updated_at desc)
    where deleted_at is null;

create table if not exists public.prospecta_message_bot_configs (
    id uuid primary key default gen_random_uuid(),
    slug text not null,
    name text not null,
    created_by uuid not null,
    lead_owner_id uuid not null,
    whatsapp_session_id uuid not null
        references public.prospecta_whatsapp_sessions(id) on delete restrict,
    niche text not null,
    source_stage_id uuid not null
        references public.lead_stages(id) on delete restrict,
    target_stage_id uuid not null
        references public.lead_stages(id) on delete restrict,
    message_template text not null,
    min_interval_seconds integer not null,
    max_interval_seconds integer not null,
    max_messages_per_hour integer not null,
    weekly_schedule jsonb not null,
    timezone text not null default 'America/Sao_Paulo',
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint prospecta_message_bots_slug_format
        check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    constraint prospecta_message_bots_name_not_blank
        check (btrim(name) <> ''),
    constraint prospecta_message_bots_niche_not_blank
        check (btrim(niche) <> ''),
    constraint prospecta_message_bots_message_not_blank
        check (btrim(message_template) <> ''),
    constraint prospecta_message_bots_intervals_valid
        check (
            min_interval_seconds >= 60
            and max_interval_seconds >= min_interval_seconds
            and max_interval_seconds <= 2592000
        ),
    constraint prospecta_message_bots_hourly_limit_valid
        check (max_messages_per_hour between 1 and 100),
    constraint prospecta_message_bots_schedule_object
        check (jsonb_typeof(weekly_schedule) = 'object'),
    constraint prospecta_message_bots_timezone_valid
        check (timezone = 'America/Sao_Paulo'),
    constraint prospecta_message_bots_stage_transition_valid
        check (source_stage_id <> target_stage_id)
);

create unique index if not exists prospecta_message_bots_slug_active_uidx
    on public.prospecta_message_bot_configs (slug)
    where deleted_at is null;
create index if not exists prospecta_message_bots_owner_niche_idx
    on public.prospecta_message_bot_configs (
        lead_owner_id, niche, source_stage_id
    )
    where deleted_at is null;
create index if not exists prospecta_message_bots_session_idx
    on public.prospecta_message_bot_configs (whatsapp_session_id)
    where deleted_at is null;

create table if not exists public.prospecta_message_bot_controls (
    bot_id uuid primary key
        references public.prospecta_message_bot_configs(id) on delete cascade,
    command text not null,
    target_runner_id text,
    request_id uuid not null default gen_random_uuid(),
    requested_at timestamptz not null default now(),
    acknowledged_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prospecta_message_controls_command_valid
        check (command in ('rodando', 'pausado', 'parado'))
);

create index if not exists prospecta_message_controls_runner_idx
    on public.prospecta_message_bot_controls (
        target_runner_id, requested_at desc
    );

create table if not exists public.prospecta_message_bot_runtime (
    bot_id uuid primary key
        references public.prospecta_message_bot_configs(id) on delete cascade,
    runner_id text,
    status text not null default 'idle',
    sent_count bigint not null default 0,
    invalid_count bigint not null default 0,
    failed_count bigint not null default 0,
    current_lead_id uuid,
    next_send_at timestamptz,
    heartbeat_at timestamptz,
    last_sent_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prospecta_message_runtime_status_valid
        check (status in (
            'idle', 'starting', 'waiting_qr', 'running', 'paused',
            'outside_schedule', 'hourly_limit', 'no_leads', 'stopped', 'failed'
        ))
);

create table if not exists public.prospecta_message_deliveries (
    id bigint generated always as identity primary key,
    bot_id uuid not null
        references public.prospecta_message_bot_configs(id) on delete cascade,
    lead_id uuid not null references public.leads(id) on delete cascade,
    whatsapp_session_id uuid not null
        references public.prospecta_whatsapp_sessions(id) on delete restrict,
    phone_normalized text not null,
    status text not null default 'claimed',
    claim_token uuid not null default gen_random_uuid(),
    claimed_by text not null,
    lease_expires_at timestamptz not null,
    attempt_count integer not null default 1,
    error_code text,
    sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prospecta_message_deliveries_status_valid
        check (status in ('claimed', 'sent', 'invalid', 'failed')),
    constraint prospecta_message_deliveries_phone_not_blank
        check (btrim(phone_normalized) <> '')
);

create unique index if not exists prospecta_message_delivery_bot_lead_uidx
    on public.prospecta_message_deliveries (bot_id, lead_id);
create index if not exists prospecta_message_delivery_bot_sent_idx
    on public.prospecta_message_deliveries (bot_id, sent_at desc)
    where status = 'sent';
create index if not exists prospecta_message_delivery_claim_idx
    on public.prospecta_message_deliveries (
        bot_id, status, lease_expires_at
    );

create or replace function public.prospecta_touch_message_versioned_row()
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

create or replace function public.prospecta_touch_message_row()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    new.updated_at := clock_timestamp();
    return new;
end;
$$;

drop trigger if exists prospecta_whatsapp_sessions_touch
    on public.prospecta_whatsapp_sessions;
create trigger prospecta_whatsapp_sessions_touch
before update on public.prospecta_whatsapp_sessions
for each row execute function public.prospecta_touch_message_versioned_row();

drop trigger if exists prospecta_message_configs_touch
    on public.prospecta_message_bot_configs;
create trigger prospecta_message_configs_touch
before update on public.prospecta_message_bot_configs
for each row execute function public.prospecta_touch_message_versioned_row();

drop trigger if exists prospecta_message_controls_touch
    on public.prospecta_message_bot_controls;
create trigger prospecta_message_controls_touch
before update on public.prospecta_message_bot_controls
for each row execute function public.prospecta_touch_message_row();

drop trigger if exists prospecta_message_runtime_touch
    on public.prospecta_message_bot_runtime;
create trigger prospecta_message_runtime_touch
before update on public.prospecta_message_bot_runtime
for each row execute function public.prospecta_touch_message_row();

drop trigger if exists prospecta_message_deliveries_touch
    on public.prospecta_message_deliveries;
create trigger prospecta_message_deliveries_touch
before update on public.prospecta_message_deliveries
for each row execute function public.prospecta_touch_message_row();

create or replace function public.prospecta_can_access_message_bot(
    p_bot_id uuid
)
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
            from public.prospecta_message_bot_configs config
            where config.id = p_bot_id
              and config.deleted_at is null
              and (
                  config.created_by = auth.uid()
                  or public.prospecta_is_admin(auth.uid())
              )
        );
$$;

create or replace function public.prospecta_list_message_bot_runtimes()
returns table (runtime jsonb)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select jsonb_build_object(
        'config', to_jsonb(config),
        'session', to_jsonb(session),
        'control', to_jsonb(control),
        'runtime', to_jsonb(bot_runtime)
    )
    from public.prospecta_message_bot_configs config
    join public.prospecta_whatsapp_sessions session
      on session.id = config.whatsapp_session_id
    left join public.prospecta_message_bot_controls control
      on control.bot_id = config.id
    left join public.prospecta_message_bot_runtime bot_runtime
      on bot_runtime.bot_id = config.id
    where config.deleted_at is null
      and session.deleted_at is null
      and public.prospecta_can_access_message_bot(config.id)
    order by config.name;
$$;

create or replace function public.prospecta_list_message_niches(
    p_owner_id uuid
)
returns table (niche text)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select distinct btrim(lead.value) as niche
    from (
        select owner_id, source as value from public.leads
        union all
        select owner_id, niche as value from public.leads
    ) lead
    where lead.owner_id = p_owner_id
      and btrim(coalesce(lead.value, '')) <> ''
      and (
          auth.uid() is null
          or auth.uid() = p_owner_id
          or public.prospecta_is_admin(auth.uid())
      )
    order by niche;
$$;

create or replace function public.prospecta_request_message_bot_command(
    p_bot_id uuid,
    p_command text,
    p_target_runner_id text default null
)
returns setof public.prospecta_message_bot_controls
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if p_command not in ('rodando', 'pausado', 'parado') then
        raise exception 'Comando inválido';
    end if;
    if not public.prospecta_can_access_message_bot(p_bot_id) then
        raise exception 'Acesso negado ao bot';
    end if;
    if p_command = 'rodando'
       and btrim(coalesce(p_target_runner_id, '')) = '' then
        raise exception 'Executor é obrigatório para iniciar';
    end if;
    if p_command = 'rodando' and exists (
        select 1
        from public.prospecta_message_bot_configs config
        join public.prospecta_whatsapp_sessions session
          on session.id = config.whatsapp_session_id
        where config.id = p_bot_id
          and session.runner_id is not null
          and session.status in ('connecting', 'qr_pending', 'ready')
          and session.last_seen_at >= clock_timestamp() - interval '2 minutes'
          and session.runner_id <> p_target_runner_id
    ) then
        raise exception 'A sessão está conectada em outro executor';
    end if;

    return query
    insert into public.prospecta_message_bot_controls (
        bot_id, command, target_runner_id, request_id,
        requested_at, acknowledged_at
    )
    values (
        p_bot_id, p_command, nullif(btrim(p_target_runner_id), ''),
        gen_random_uuid(), clock_timestamp(), null
    )
    on conflict (bot_id) do update
    set command = excluded.command,
        target_runner_id = coalesce(
            excluded.target_runner_id,
            prospecta_message_bot_controls.target_runner_id
        ),
        request_id = excluded.request_id,
        requested_at = excluded.requested_at,
        acknowledged_at = null
    returning prospecta_message_bot_controls.*;
end;
$$;

create or replace function public.prospecta_claim_message_lead(
    p_bot_id uuid,
    p_runner_id text,
    p_lease_seconds integer default 300
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    v_config public.prospecta_message_bot_configs%rowtype;
    v_delivery public.prospecta_message_deliveries%rowtype;
    v_lead public.leads%rowtype;
    v_phone text;
begin
    if btrim(coalesce(p_runner_id, '')) = '' then
        raise exception 'Executor é obrigatório';
    end if;
    if p_lease_seconds < 60 or p_lease_seconds > 3600 then
        raise exception 'Lease inválido';
    end if;

    select *
    into v_config
    from public.prospecta_message_bot_configs
    where id = p_bot_id and deleted_at is null;

    if not found then
        return null;
    end if;

    if not exists (
        select 1
        from public.prospecta_message_bot_controls control
        where control.bot_id = p_bot_id
          and control.command = 'rodando'
          and control.target_runner_id = p_runner_id
    ) then
        return null;
    end if;

    select delivery.*
    into v_delivery
    from public.prospecta_message_deliveries delivery
    where delivery.bot_id = p_bot_id
      and delivery.status = 'claimed'
      and delivery.lease_expires_at < clock_timestamp()
    order by delivery.created_at
    for update skip locked
    limit 1;

    if found then
        update public.prospecta_message_deliveries
        set claim_token = gen_random_uuid(),
            claimed_by = p_runner_id,
            lease_expires_at = clock_timestamp()
                + make_interval(secs => p_lease_seconds),
            attempt_count = attempt_count + 1
        where id = v_delivery.id
        returning * into v_delivery;

        select * into v_lead
        from public.leads
        where id = v_delivery.lead_id;
        if not found
           or v_lead.owner_id is distinct from v_config.lead_owner_id
           or not (
               coalesce(v_lead.niche, '') = v_config.niche
               or coalesce(v_lead.source, '') = v_config.niche
           )
           or v_lead.stage_id is distinct from v_config.source_stage_id
           or coalesce(v_lead.whatsapp_do_not_contact, false) then
            update public.prospecta_message_deliveries
            set status = 'failed',
                error_code = 'lead_no_longer_eligible',
                lease_expires_at = clock_timestamp()
            where id = v_delivery.id;
            return null;
        end if;
    else
        select lead.*
        into v_lead
        from public.leads lead
        where lead.owner_id = v_config.lead_owner_id
          and (
              coalesce(lead.niche, '') = v_config.niche
              or coalesce(lead.source, '') = v_config.niche
          )
          and lead.stage_id = v_config.source_stage_id
          and not coalesce(lead.whatsapp_do_not_contact, false)
          and btrim(coalesce(nullif(lead.whatsapp, ''), lead.phone, '')) <> ''
          and not exists (
              select 1
              from public.prospecta_message_deliveries delivery
              where delivery.bot_id = p_bot_id
                and delivery.lead_id = lead.id
          )
        order by lead.created_at, lead.id
        for update skip locked
        limit 1;

        if not found then
            return null;
        end if;

        v_phone := coalesce(nullif(v_lead.whatsapp, ''), v_lead.phone);
        insert into public.prospecta_message_deliveries (
            bot_id, lead_id, whatsapp_session_id, phone_normalized,
            claimed_by, lease_expires_at
        )
        values (
            p_bot_id, v_lead.id, v_config.whatsapp_session_id,
            regexp_replace(v_phone, '[^0-9]', '', 'g'),
            p_runner_id,
            clock_timestamp() + make_interval(secs => p_lease_seconds)
        )
        returning * into v_delivery;
    end if;

    return jsonb_build_object(
        'delivery_id', v_delivery.id,
        'claim_token', v_delivery.claim_token,
        'lead_id', v_lead.id,
        'name', v_lead.name,
        'company', v_lead.company,
        'niche', v_config.niche,
        'phone', coalesce(nullif(v_lead.whatsapp, ''), v_lead.phone)
    );
end;
$$;

create or replace function public.prospecta_finalize_message_delivery(
    p_delivery_id bigint,
    p_claim_token uuid,
    p_status text,
    p_error_code text default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    v_delivery public.prospecta_message_deliveries%rowtype;
    v_target_stage uuid;
begin
    if p_status not in ('sent', 'invalid', 'failed') then
        raise exception 'Status final inválido';
    end if;

    select *
    into v_delivery
    from public.prospecta_message_deliveries
    where id = p_delivery_id
      and claim_token = p_claim_token
      and status = 'claimed'
    for update;

    if not found then
        return false;
    end if;

    update public.prospecta_message_deliveries
    set status = p_status,
        error_code = left(nullif(p_error_code, ''), 200),
        sent_at = case when p_status = 'sent'
            then clock_timestamp() else null end,
        lease_expires_at = clock_timestamp()
    where id = p_delivery_id;

    if p_status = 'sent' then
        select target_stage_id
        into v_target_stage
        from public.prospecta_message_bot_configs
        where id = v_delivery.bot_id;

        update public.leads
        set stage_id = v_target_stage,
            updated_at = clock_timestamp()
        where id = v_delivery.lead_id;
    end if;

    insert into public.prospecta_message_bot_runtime (
        bot_id, sent_count, invalid_count, failed_count
    )
    values (
        v_delivery.bot_id,
        case when p_status = 'sent' then 1 else 0 end,
        case when p_status = 'invalid' then 1 else 0 end,
        case when p_status = 'failed' then 1 else 0 end
    )
    on conflict (bot_id) do update
    set sent_count = prospecta_message_bot_runtime.sent_count
            + case when p_status = 'sent' then 1 else 0 end,
        invalid_count = prospecta_message_bot_runtime.invalid_count
            + case when p_status = 'invalid' then 1 else 0 end,
        failed_count = prospecta_message_bot_runtime.failed_count
            + case when p_status = 'failed' then 1 else 0 end;

    return true;
end;
$$;

create or replace function public.prospecta_message_sent_last_hour(
    p_bot_id uuid
)
returns integer
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
    select count(*)::integer
    from public.prospecta_message_deliveries
    where bot_id = p_bot_id
      and status = 'sent'
      and sent_at >= clock_timestamp() - interval '1 hour';
$$;

alter table public.prospecta_whatsapp_sessions enable row level security;
alter table public.prospecta_message_bot_configs enable row level security;
alter table public.prospecta_message_bot_controls enable row level security;
alter table public.prospecta_message_bot_runtime enable row level security;
alter table public.prospecta_message_deliveries enable row level security;

grant select, insert, update on public.prospecta_whatsapp_sessions
    to authenticated, service_role;
grant select, insert, update on public.prospecta_message_bot_configs
    to authenticated, service_role;
grant select, insert, update on public.prospecta_message_bot_controls
    to service_role;
grant select, insert, update on public.prospecta_message_bot_runtime
    to service_role;
grant select, insert, update on public.prospecta_message_deliveries
    to service_role;
grant usage, select on sequence public.prospecta_message_deliveries_id_seq
    to service_role;

drop policy if exists prospecta_whatsapp_sessions_scope
    on public.prospecta_whatsapp_sessions;
create policy prospecta_whatsapp_sessions_scope
on public.prospecta_whatsapp_sessions
for all to authenticated
using (
    owner_id = auth.uid() or public.prospecta_is_admin(auth.uid())
)
with check (
    owner_id = auth.uid() or public.prospecta_is_admin(auth.uid())
);

drop policy if exists prospecta_message_configs_scope
    on public.prospecta_message_bot_configs;
create policy prospecta_message_configs_scope
on public.prospecta_message_bot_configs
for all to authenticated
using (
    created_by = auth.uid()
    or public.prospecta_is_admin(auth.uid())
)
with check (
    public.prospecta_is_admin(auth.uid())
    or (
        created_by = auth.uid()
        and lead_owner_id = auth.uid()
        and exists (
            select 1
            from public.prospecta_whatsapp_sessions session
            where session.id = whatsapp_session_id
              and session.owner_id = auth.uid()
              and session.deleted_at is null
        )
    )
);

drop policy if exists prospecta_message_controls_select_scope
    on public.prospecta_message_bot_controls;
create policy prospecta_message_controls_select_scope
on public.prospecta_message_bot_controls
for select to authenticated
using (public.prospecta_can_access_message_bot(bot_id));

drop policy if exists prospecta_message_runtime_select_scope
    on public.prospecta_message_bot_runtime;
create policy prospecta_message_runtime_select_scope
on public.prospecta_message_bot_runtime
for select to authenticated
using (public.prospecta_can_access_message_bot(bot_id));

drop policy if exists prospecta_message_deliveries_select_scope
    on public.prospecta_message_deliveries;
create policy prospecta_message_deliveries_select_scope
on public.prospecta_message_deliveries
for select to authenticated
using (public.prospecta_can_access_message_bot(bot_id));

revoke all on function public.prospecta_can_access_message_bot(uuid)
    from public, anon, authenticated;
revoke all on function public.prospecta_list_message_bot_runtimes()
    from public, anon, authenticated;
revoke all on function public.prospecta_list_message_niches(uuid)
    from public, anon, authenticated;
revoke all on function public.prospecta_request_message_bot_command(uuid, text, text)
    from public, anon, authenticated;
revoke all on function public.prospecta_claim_message_lead(uuid, text, integer)
    from public, anon, authenticated;
revoke all on function public.prospecta_finalize_message_delivery(bigint, uuid, text, text)
    from public, anon, authenticated;
revoke all on function public.prospecta_message_sent_last_hour(uuid)
    from public, anon, authenticated;

grant execute on function public.prospecta_can_access_message_bot(uuid)
    to authenticated, service_role;
grant execute on function public.prospecta_list_message_bot_runtimes()
    to authenticated, service_role;
grant execute on function public.prospecta_list_message_niches(uuid)
    to authenticated, service_role;
grant execute on function public.prospecta_request_message_bot_command(uuid, text, text)
    to authenticated, service_role;
grant execute on function public.prospecta_claim_message_lead(uuid, text, integer)
    to service_role;
grant execute on function public.prospecta_finalize_message_delivery(bigint, uuid, text, text)
    to service_role;
grant execute on function public.prospecta_message_sent_last_hour(uuid)
    to service_role;

revoke all on function public.prospecta_touch_message_versioned_row()
    from public, anon, authenticated;
revoke all on function public.prospecta_touch_message_row()
    from public, anon, authenticated;

notify pgrst, 'reload schema';

commit;

-- Índices compatíveis com a execução transacional do SQL Editor do Supabase.
create index if not exists prospecta_leads_message_eligibility_idx
    on public.leads (owner_id, source, stage_id, created_at)
    where not whatsapp_do_not_contact
      and (phone is not null or whatsapp is not null);

create index if not exists prospecta_leads_message_niche_idx
    on public.leads (owner_id, niche, stage_id, created_at)
    where not whatsapp_do_not_contact
      and (phone is not null or whatsapp is not null);
