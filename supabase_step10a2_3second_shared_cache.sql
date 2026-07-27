-- =========================================================
-- KTX 빈자리 모니터 Step 10A.2
-- 사용자 작업 3초 허용 + 동일 열차 결과 공유 캐시
-- =========================================================

create or replace function public.activate_monitor_job_live(
    p_job_id uuid
)
returns public.monitor_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    current_user_id uuid;
    total_active_count integer;
    live_active_count integer;
    result_row public.monitor_jobs;
begin
    current_user_id := (select auth.uid());

    if current_user_id is null then
        raise exception '로그인이 필요합니다.';
    end if;

    if not exists (
        select 1
        from public.profiles
        where id = current_user_id
and telegram_chat_id is not null
and length(trim(telegram_chat_id)) > 0
    ) then
        raise exception 'Telegram 연결이 필요합니다.';
    end if;

    if not exists (
        select 1
        from public.monitor_jobs
        where id = p_job_id
and user_id = current_user_id
and check_interval_seconds >= 3
    ) then
        raise exception '실제 페이지 모니터링 간격은 3초 이상이어야 합니다.';
    end if;

    select count(*)
    into total_active_count
    from public.monitor_jobs
    where user_id = current_user_id
      and status = 'active'
      and is_enabled = true
      and id <> p_job_id;

    if total_active_count >= 3 then
        raise exception '동시에 실행 가능한 작업은 최대 3개입니다.';
    end if;

    select count(*)
    into live_active_count
    from public.monitor_jobs
    where user_id = current_user_id
      and status = 'active'
      and is_enabled = true
      and provider = 'korail_web'
      and id <> p_job_id;

    if live_active_count >= 1 then
        raise exception '실제 좌석 작업은 최대 1개만 동시에 실행할 수 있습니다.';
    end if;

    update public.monitor_jobs
    set
        status = 'active',
        is_enabled = true,
        provider = 'korail_web',
        worker_check_count = 0,
        next_check_at = now(),
        locked_at = null,
        lock_token = null,
        last_checked_at = null,
        last_result = null,
        last_error = null,
        alert_sent_at = null,
        completed_reason = null,
        worker_version = null
    where id = p_job_id
      and user_id = current_user_id
      and departure_planned_at > now()
    returning * into result_row;

    if result_row.id is null then
        raise exception '작업을 찾지 못했거나 이미 출발한 열차입니다.';
    end if;

    return result_row;
end;
$$;

revoke all on function public.activate_monitor_job_live(uuid)
from public, anon;

grant execute on function public.activate_monitor_job_live(uuid)
to authenticated;

select
    routine_name
from information_schema.routines
where routine_schema = 'public'
  and routine_name = 'activate_monitor_job_live';
