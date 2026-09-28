import pluginExample from "./assets/images/dialogue/plugin-example.png"
import pluginCar from "./assets/images/dialogue/plugin-car.png"
import pluginPerson from "./assets/images/dialogue/plugin-person.png"
import pluginNight from "./assets/images/dialogue/plugin-night.png"
import pluginLink from "./assets/images/dialogue/plugin-link.png"
import pluginFunds from "./assets/images/dialogue/plugin-funds.png"
import pluginCombined from "./assets/images/dialogue/plugin-combined.png"
import pluginCall from "./assets/images/dialogue/plugin-call.png"
import graphPolice from "./assets/images/dialogue/graph-police.png"
import clueObservation from "./assets/images/dialogue/clue-observation.png"
import cluePlace from "./assets/images/dialogue/clue-place.png"
import clueVehicle from "./assets/images/dialogue/clue-vehicle.png"
import cluePerson from "./assets/images/dialogue/clue-person.png"
import clueNight from "./assets/images/dialogue/clue-night.png"
import clueFunds from "./assets/images/dialogue/clue-funds.png"
import document from "./assets/images/dialogue/document.png"
import sectionEvidence from "./assets/images/dialogue/section-evidence.png"
import sectionFinding from "./assets/images/dialogue/section-finding.png"
import sectionSummary from "./assets/images/dialogue/section-summary.png"
import zoomIn from "./assets/images/dialogue/zoom-in.png"

export const dialogueIcons = { graphPolice, document, sectionEvidence, sectionFinding, sectionSummary, zoomIn }

export function pluginIcon(name: string) {
  const value = name.toLowerCase()
  if (/话单|call|phone/.test(value)) return pluginCall
  if (/资金|fund|payment/.test(value)) return pluginFunds
  if (/夜间|night/.test(value)) return pluginNight
  if (/人像|人员|person|companion/.test(value)) return pluginPerson
  if (/车辆|vehicle|car/.test(value)) return pluginCar
  if (/互查|关系|link/.test(value)) return pluginLink
  if (/综合|关联|combined/.test(value)) return pluginCombined
  return pluginExample
}

export function clueTheme(type: string, title: string) {
  const value = `${type} ${title}`.toLowerCase()
  if (/资金|fund|money|finance|account/.test(value)) return "funds"
  if (/夜间|night|trajectory/.test(value)) return "night"
  if (/车辆|vehicle|car/.test(value)) return "vehicle"
  if (/地点|place|location/.test(value)) return "place"
  if (/人员|同行|person|companion/.test(value)) return "person"
  if (/观测|状态|capture|observation/.test(value)) return "observation"
  return "observation"
}

export function clueIcon(type: string, title: string) {
  const theme = clueTheme(type, title)
  return { funds: clueFunds, night: clueNight, vehicle: clueVehicle, place: cluePlace, person: cluePerson, observation: clueObservation }[theme]
}
