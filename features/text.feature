Feature: In-shape text via TextFrame
  In order to author labelled shapes
  As a vsdx developer
  I want shape.text and shape.text_frame to round-trip
  string content reliably

  Background:
    Given a fresh blank document with one page

  Scenario: A fresh shape with no text exposes an empty TextFrame
     When I add a Rectangle at (2, 5) sized (2, 1)
     Then the shape exposes a text_frame
      And the text_frame text is empty

  Scenario: Set text via the shape shortcut
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I set the shape text to "Architecture"
     Then the shape's text reads back as "Architecture"
      And the shape exposes has_text_frame True

  Scenario: Set text via TextFrame.text
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I set the text_frame text to "Round-trip"
     Then the shape's text reads back as "Round-trip"

  Scenario: TextFrame paragraphs returns one paragraph in 0.1.0
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I set the shape text to "Hi"
     Then the text_frame paragraphs list has length 1

  Scenario: TextFrame.clear empties the text content
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I set the shape text to "Goodbye"
      And I clear the text_frame
     Then the shape's text reads back as ""

  Scenario: Round-trip text content through a saved buffer
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I set the shape text to "Persisted"
      And I save the document and re-open from the buffer
     Then the re-opened first shape's text reads back as "Persisted"

  @wip
  Scenario: Multiple paragraphs are emitted as separate runs
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I add two paragraphs to the text_frame
     Then the text_frame paragraphs list has length 2

  @wip
  Scenario: Per-run formatting persists across save / re-open
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I add a bold red run to the shape
      And I save the document and re-open from the buffer
     Then the re-opened first run reads back as bold red
