package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/asheshgoplani/agent-deck/internal/session"
	"github.com/asheshgoplani/agent-deck/internal/tmux"
)

const releaseQualificationReceiptMaxBytes = 2048

type releaseQualificationAcceptedTurn struct {
	ReceiptID      string `json:"receipt_id"`
	InstanceID     string `json:"instance_id"`
	CodexSessionID string `json:"codex_session_id"`
	TurnGeneration string `json:"turn_generation"`
	AcceptedAt     string `json:"accepted_at"`
}

type releaseQualificationReceipt struct {
	SchemaVersion    int                               `json:"schema_version"`
	Success          bool                              `json:"success"`
	Acceptance       string                            `json:"acceptance"`
	Code             string                            `json:"code,omitempty"`
	InstanceID       string                            `json:"instance_id,omitempty"`
	Delivery         string                            `json:"delivery,omitempty"`
	Submitted        *bool                             `json:"submitted,omitempty"`
	AcceptedTurnKind string                            `json:"accepted_turn_kind,omitempty"`
	AcceptedTurn     *releaseQualificationAcceptedTurn `json:"accepted_turn,omitempty"`
}

func validateReleaseQualificationReceipt(raw []byte) error {
	if len(raw)+1 > releaseQualificationReceiptMaxBytes {
		return fmt.Errorf("receipt is %d bytes including newline", len(raw)+1)
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var receipt releaseQualificationReceipt
	if err := decoder.Decode(&receipt); err != nil {
		return fmt.Errorf("receipt schema: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return fmt.Errorf("receipt has trailing JSON")
	}
	if receipt.SchemaVersion != 1 {
		return fmt.Errorf("receipt schema version is not 1")
	}
	if receipt.Success {
		if receipt.Acceptance != "accepted" || receipt.Code != "" ||
			receipt.InstanceID == "" || receipt.Delivery != "submitted" ||
			receipt.Submitted == nil || !*receipt.Submitted ||
			receipt.AcceptedTurnKind != "codex_rollout" || receipt.AcceptedTurn == nil ||
			receipt.AcceptedTurn.InstanceID != receipt.InstanceID ||
			receipt.AcceptedTurn.ReceiptID == "" ||
			receipt.AcceptedTurn.CodexSessionID == "" ||
			receipt.AcceptedTurn.TurnGeneration == "" ||
			receipt.AcceptedTurn.AcceptedAt == "" {
			return fmt.Errorf("accepted receipt invariants failed")
		}
		return nil
	}
	if receipt.Acceptance != "not_accepted" && receipt.Acceptance != "indeterminate" {
		return fmt.Errorf("failure acceptance is invalid")
	}
	if receipt.Code == "" || receipt.AcceptedTurnKind != "" || receipt.AcceptedTurn != nil {
		return fmt.Errorf("failure receipt fields are invalid")
	}
	if receipt.Delivery == "" {
		if receipt.Submitted != nil {
			return fmt.Errorf("failure submission lacks delivery")
		}
		return nil
	}
	if receipt.Submitted == nil || *receipt.Submitted != (receipt.Delivery == "submitted") {
		return fmt.Errorf("failure delivery and submission disagree")
	}
	return nil
}

type releaseQualificationFreshLaunchOps struct {
	instanceID string
	readyErr   error
	verdict    acceptanceOnlyResult
	sends      int
}

func (o *releaseQualificationFreshLaunchOps) InstanceID() string        { return o.instanceID }
func (o *releaseQualificationFreshLaunchOps) PrepareFreshFence() error  { return nil }
func (o *releaseQualificationFreshLaunchOps) WaitReady() error          { return o.readyErr }
func (o *releaseQualificationFreshLaunchOps) ValidateFreshFence() error { return nil }
func (o *releaseQualificationFreshLaunchOps) ReserveSubmission() error  { return nil }
func (o *releaseQualificationFreshLaunchOps) SendOnce() (string, error) {
	o.sends++
	return deliveryDelivered, nil
}
func (o *releaseQualificationFreshLaunchOps) RecordTransportOutcome(string) error { return nil }
func (o *releaseQualificationFreshLaunchOps) AcceptedVerdict(string) acceptanceOnlyResult {
	return o.verdict
}
func (o *releaseQualificationFreshLaunchOps) Release() {}

func TestReleaseQualificationFreshLaunchAcceptance(t *testing.T) {
	const instanceID = "fixture-instance"

	t.Run("accepted_exact_first_turn_once", func(t *testing.T) {
		receipt := &codexAcceptedTurnReceipt{
			ReceiptID:      "01234567-89ab-4cde-8fab-0123456789ab",
			InstanceID:     instanceID,
			CodexSessionID: "fixture-codex-session",
			TurnGeneration: "fixture-codex-session:fixture-first-turn",
			AcceptedAt:     time.Date(2026, 9, 24, 0, 0, 0, 0, time.UTC).Format(time.RFC3339Nano),
		}
		accepted, err := newAcceptanceOnlySuccessResult(receipt)
		if err != nil {
			t.Fatal(err)
		}
		ops := &releaseQualificationFreshLaunchOps{instanceID: instanceID, verdict: accepted}
		result := runFreshLaunchAcceptance(ops)
		if !result.Success || result.InstanceID != instanceID || result.AcceptedTurn == nil || ops.sends != 1 {
			t.Fatalf("result=%#v sends=%d", result, ops.sends)
		}
		raw, err := marshalAcceptanceOnlyResult(result)
		if err != nil {
			t.Fatalf("unsafe accepted result: bytes=%d err=%v", len(raw)+1, err)
		}
		if err := validateReleaseQualificationReceipt(raw); err != nil {
			t.Fatalf("unsafe accepted result: %v", err)
		}
	})

	t.Run("post_creation_uncertainty_retains_identity_without_retry", func(t *testing.T) {
		ops := &releaseQualificationFreshLaunchOps{
			instanceID: instanceID,
			verdict: newAcceptanceOnlyFailureResult(
				acceptanceOnlyCodeIndeterminate,
				acceptanceOnlyIndeterminate,
				deliveryDelivered,
			),
		}
		result := runFreshLaunchAcceptance(ops)
		if result.Success || result.Acceptance != acceptanceOnlyIndeterminate || result.InstanceID != instanceID || ops.sends != 1 {
			t.Fatalf("result=%#v sends=%d", result, ops.sends)
		}
		raw, err := marshalAcceptanceOnlyResult(result)
		if err != nil {
			t.Fatalf("unsafe uncertain result: bytes=%d err=%v", len(raw)+1, err)
		}
		if err := validateReleaseQualificationReceipt(raw); err != nil {
			t.Fatalf("unsafe uncertain result: %v", err)
		}

		beforeTransport := &releaseQualificationFreshLaunchOps{
			instanceID: instanceID,
			readyErr:   errors.New("process exited"),
		}
		result = runFreshLaunchAcceptance(beforeTransport)
		if result.Success || result.InstanceID != instanceID || beforeTransport.sends != 0 {
			t.Fatalf("pre-transport result=%#v sends=%d", result, beforeTransport.sends)
		}
		raw, err = marshalAcceptanceOnlyResult(result)
		if err != nil {
			t.Fatal(err)
		}
		if err := validateReleaseQualificationReceipt(raw); err != nil {
			t.Fatalf("unsafe pre-transport result: %v", err)
		}
	})

	t.Run("invalid_input_rejected_before_spawn", func(t *testing.T) {
		if err := validateLaunchAcceptanceRequest(launchAcceptanceRequest{
			message: "fixture prompt",
			tool:    "codex",
		}); err != nil {
			t.Fatalf("valid request rejected: %v", err)
		}
		if err := validateLaunchAcceptanceRequest(launchAcceptanceRequest{tool: "codex"}); err == nil {
			t.Fatal("missing initial message was accepted")
		}
	})

	t.Run("actual_private_transport_once", func(t *testing.T) {
		const shim = `#!/bin/sh
umask 077
printf '%s\n' "$@" >> "$AD_QUALIFICATION_DIR/argv"
env >> "$AD_QUALIFICATION_DIR/env"
verb=
for item in "$@"; do
    case "$item" in load-buffer|paste-buffer|send-keys|display-message|delete-buffer) verb=$item; break;; esac
done
case "$verb" in
    display-message) printf '%%987\n';;
    load-buffer) cat > "$AD_QUALIFICATION_DIR/stdin";;
    paste-buffer) if [ "$AD_QUALIFICATION_MODE" = paste ]; then exit 1; fi;;
    send-keys) if [ "$AD_QUALIFICATION_MODE" = enter ]; then exit 1; fi;;
esac
exit 0
`
		originalPath := os.Getenv("PATH")
		bodies := []struct {
			name  string
			value string
		}{
			{name: "short", value: "qualification-private-body-short"},
			{name: "long", value: strings.Repeat("qualification-private-body-long ", 80)},
			{name: "multiline", value: "qualification-private-body-line-one\n" + strings.Repeat("qualification-private-body-middle\n", 80)},
		}
		for _, body := range bodies {
			for _, mode := range []string{"success", "paste", "enter"} {
				root := t.TempDir()
				if err := os.WriteFile(filepath.Join(root, "tmux"), []byte(shim), 0o700); err != nil {
					t.Fatal(err)
				}
				t.Setenv("PATH", root+string(os.PathListSeparator)+originalPath)
				t.Setenv("AD_QUALIFICATION_DIR", root)
				t.Setenv("AD_QUALIFICATION_MODE", mode)
				t.Setenv("XDG_DATA_HOME", filepath.Join(root, "data"))

				inst := &session.Instance{ID: "qualification-instance", Tool: "codex"}
				inst.SetTmuxSessionForTest(&tmux.Session{
					Name: "qualification-pane", SocketName: "qualification-socket",
				})
				delivery, sendErr := (&liveFreshLaunchAcceptanceOps{
					inst: inst, message: body.value,
				}).SendOnce()
				if mode == "success" {
					if sendErr != nil || delivery != deliveryDelivered {
						t.Fatalf("%s/%s: delivery=%q err=%v", body.name, mode, delivery, sendErr)
					}
				} else if sendErr == nil || delivery != deliverySendFailed {
					t.Fatalf("%s/%s: delivery=%q err=%v", body.name, mode, delivery, sendErr)
				}
				if sendErr != nil && strings.Contains(sendErr.Error(), "qualification-private-body") {
					t.Fatalf("%s/%s: prompt leaked in error", body.name, mode)
				}

				read := func(name string) string {
					raw, err := os.ReadFile(filepath.Join(root, name))
					if err != nil {
						t.Fatal(err)
					}
					return string(raw)
				}
				argv, environment, stdin := read("argv"), read("env"), read("stdin")
				if strings.Contains(argv, "qualification-private-body") ||
					strings.Contains(environment, "qualification-private-body") {
					t.Fatalf("%s/%s: prompt leaked outside private stdin", body.name, mode)
				}
				if stdin != body.value {
					t.Fatalf("%s/%s: private stdin did not receive exact prompt", body.name, mode)
				}
				counts := map[string]int{}
				for _, argument := range strings.Split(argv, "\n") {
					counts[argument]++
				}
				wantEnter := 1
				if mode == "paste" {
					wantEnter = 0
				}
				if counts["load-buffer"] != 1 || counts["paste-buffer"] != 1 ||
					counts["Enter"] != wantEnter || counts["-l"] != 0 {
					t.Fatalf(
						"%s/%s: transport repeated or unsafe: load=%d paste=%d enter=%d literal=%d",
						body.name, mode, counts["load-buffer"], counts["paste-buffer"],
						counts["Enter"], counts["-l"],
					)
				}
				if !strings.Contains(argv, "qualification-pane:^") && !strings.Contains(argv, "%987") {
					t.Fatalf("%s/%s: private transport did not select managed window", body.name, mode)
				}
				lock, err := session.AcquireSendLock(inst.ID, 20*time.Millisecond)
				if err != nil {
					t.Fatalf("%s/%s: send lock leaked: %v", body.name, mode, err)
				}
				lock.Release()
			}
		}
	})
}
