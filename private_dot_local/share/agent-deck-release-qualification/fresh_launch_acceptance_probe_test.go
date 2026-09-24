package main

import (
	"errors"
	"strings"
	"testing"
	"time"
)

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
		if err != nil || len(raw)+1 > acceptanceOnlyResultMaxBytes || strings.Contains(string(raw), "fixture prompt") {
			t.Fatalf("unsafe accepted result: bytes=%d err=%v", len(raw)+1, err)
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
		if err != nil || len(raw)+1 > acceptanceOnlyResultMaxBytes || strings.Contains(string(raw), "message") {
			t.Fatalf("unsafe uncertain result: bytes=%d err=%v", len(raw)+1, err)
		}

		beforeTransport := &releaseQualificationFreshLaunchOps{
			instanceID: instanceID,
			readyErr:   errors.New("process exited"),
		}
		result = runFreshLaunchAcceptance(beforeTransport)
		if result.Success || result.InstanceID != instanceID || beforeTransport.sends != 0 {
			t.Fatalf("pre-transport result=%#v sends=%d", result, beforeTransport.sends)
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
}
