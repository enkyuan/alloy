// Placeholder edge function
// This prevents the edge-runtime container from crash-looping
// Add your Supabase Edge Functions here

Deno.serve(async (req) => {
  return new Response(
    JSON.stringify({
      message: "Edge Functions are ready. Add your functions to docker/volumes/functions/",
    }),
    {
      headers: { "Content-Type": "application/json" },
      status: 200,
    },
  );
});
