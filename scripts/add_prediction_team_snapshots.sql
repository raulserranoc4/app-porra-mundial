ALTER TABLE predictions
ADD COLUMN IF NOT EXISTS predicted_home_team_id UUID REFERENCES teams(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS predicted_away_team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_predicted_home_team_id
ON predictions(predicted_home_team_id);

CREATE INDEX IF NOT EXISTS idx_predictions_predicted_away_team_id
ON predictions(predicted_away_team_id);
