package tmux

import "testing"

func TestReleaseQualificationCodexBusyProvenance(t *testing.T) {
	tests := []struct {
		name       string
		content    string
		wantPrompt bool
		wantBusy   bool
	}{
		{
			name:       "quoted status phrase is prose",
			content:    "Assistant result: Working (12s · esc to interrupt) was only an example.\n\n›",
			wantPrompt: true,
			wantBusy:   false,
		},
		{
			name:       "parenthesized phrase in prose is not status",
			content:    "Something in the docs says (esc to interrupt)\n› Ask Codex to do anything",
			wantPrompt: true,
			wantBusy:   false,
		},
		{
			name:       "valid occurrence after quoted occurrence is busy",
			content:    "Searching for \"esc to interrupt\" (3s • esc to interrupt)\n› previous suggestion",
			wantPrompt: false,
			wantBusy:   true,
		},
		{
			name:       "repeated valid statuses remain busy",
			content:    "Working (2s • esc to interrupt)\nReading (3s • esc to interrupt)\n› previous suggestion",
			wantPrompt: false,
			wantBusy:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := NewPromptDetector("codex").HasPrompt(tt.content); got != tt.wantPrompt {
				t.Errorf("release qualification: HasPrompt() = %v, want %v", got, tt.wantPrompt)
			}
			session := &Session{Command: "codex"}
			if got := session.hasBusyIndicator(tt.content); got != tt.wantBusy {
				t.Errorf("release qualification: hasBusyIndicator() = %v, want %v", got, tt.wantBusy)
			}
		})
	}
}
