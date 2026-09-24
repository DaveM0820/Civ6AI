include("Civ5Ai_Util")
include("Civ5Ai_Paths")
include("Civ5Ai_Config")
include("Civ5Ai_HostChannel")
-- HostInbox is a separate Lua VM from InGame. Do NOT include Civ5Ai_Bridge here:
-- Bridge.ApplyPayload needs Civ5Ai_Apply (InGame-only). Running Bridge in this VM
-- logs apply_local|no_SendCiv5AiCommands then errors before MarkApplied, leaving
-- mailboxes poisoned and spinning parse/apply while CONTROL_ENDTURN hammers with
-- a false UI can=true. InGame ExposedMembers owns apply/finish/pulse state.
Civ5Ai_Config.Initialize()
Civ5Ai_HostChannel.Initialize()
-- FPS: SetUpdate runs every frame. Sidecar mailboxes change on a human/LLM
-- timescale, so do not PumpTicks/Poll/EnsureFinishSeat 60x/sec.
local CIV5AI_HOSTINBOX_MIN_INTERVAL = 0.25
local _civ5ai_hostinbox_last = 0
if ContextPtr ~= nil and ContextPtr.SetUpdate ~= nil then
  ContextPtr:SetUpdate(function()
    local now = os.clock()
    if (now - _civ5ai_hostinbox_last) < CIV5AI_HOSTINBOX_MIN_INTERVAL then
      return
    end
    _civ5ai_hostinbox_last = now
    if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil then
      if ExposedMembers.Civ5Ai.PumpTicks ~= nil then
        ExposedMembers.Civ5Ai.PumpTicks()
      end
      if ExposedMembers.Civ5Ai.PollHostInbox ~= nil then
        ExposedMembers.Civ5Ai.PollHostInbox()
      end
      -- Applied-but-not-finished must always progress to end-turn (seat 0
      -- needs FinishSeat/CONTROL_ENDTURN; peers need FinishSeat + queue).
      if ExposedMembers.Civ5Ai.WasAppliedThisPulse ~= nil then
        for seat = 0, 3 do
          if ExposedMembers.Civ5Ai.WasAppliedThisPulse(seat) == true then
            local done = false
            if ExposedMembers.Civ5Ai.WasPulseFinished ~= nil then
              done = ExposedMembers.Civ5Ai.WasPulseFinished(seat) == true
            end
            if not done then
              if ExposedMembers.Civ5Ai.EnsureFinishSeat ~= nil then
                pcall(function()
                  ExposedMembers.Civ5Ai.EnsureFinishSeat(seat)
                end)
              elseif ExposedMembers.Civ5Ai.FinishSeat ~= nil then
                pcall(function()
                  ExposedMembers.Civ5Ai.FinishSeat(seat)
                end)
              elseif ExposedMembers.Civ5Ai.QueueFinishSeat ~= nil and seat ~= 0 then
                pcall(function()
                  ExposedMembers.Civ5Ai.QueueFinishSeat(seat)
                end)
              end
            end
          end
        end
      end
    end
    if Civ5Ai_HostChannel ~= nil and Civ5Ai_HostChannel.Poll ~= nil then
      Civ5Ai_HostChannel.Poll()
    end
  end)
  Civ5Ai_Util.Log("tick|pump_context|recovery_poll_v4")
end
