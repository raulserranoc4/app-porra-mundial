CREATE OR REPLACE FUNCTION public.prevent_group_score_events()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.category = 'group' THEN
        RETURN NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_group_score_events ON public.score_events;

CREATE TRIGGER trg_prevent_group_score_events
BEFORE INSERT OR UPDATE ON public.score_events
FOR EACH ROW
EXECUTE FUNCTION public.prevent_group_score_events();

DELETE FROM public.score_events
WHERE category = 'group';
